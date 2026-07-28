"""DB-backed tests for calibration auto-apply.

Each test builds its own farm subtree with flush() and ends with rollback() —
never commit, and never touch the globally-seeded sector (that corrupts the
local dev DB and breaks test_context_loading::test_ctx_mad_in_range).
"""
import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.calibration_policy import (
    REASON_APPLIED,
    REASON_FLATLINE,
    REASON_MANUAL_OVERRIDE,
    REASON_NO_CANDIDATE,
    REASON_PROBE_STALE,
)
from app.engine.pipeline import resolve_sector_soil_bounds
from app.models import (
    Farm,
    Plot,
    Probe,
    ProbeCalibration,
    ProbeCalibrationRun,
    ProbeDepth,
    ProbeReading,
    Sector,
    SectorCropProfile,
    User,
)
from app.services.probe_calibration_service import ProbeCalibrationService


@contextmanager
def _capture(logger_name: str):
    """Collect LogRecords from one logger.

    A plain handler rather than pytest's `caplog`: the app installs its own JSON
    logging config, and these assertions are about the record the service emits.
    """
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    target = logging.getLogger(logger_name)
    handler = _Collect(level=logging.DEBUG)
    target.addHandler(handler)
    previous_level = target.level
    target.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_sector(
    db: AsyncSession,
    *,
    vwc: float = 0.44,
    flat: bool = False,
    last_reading_age_h: float = 1.0,
    auto_apply: bool = True,
    depths_cm: tuple[int, ...] = (20,),
    constant_levels: dict[int, float] | None = None,
) -> tuple[str, str]:
    """Build Farm→Plot→Sector→Probe→ProbeDepth(s) + 60 hourly VWC readings.

    Returns (sector_id, farm_id). The plot carries the sandy_loam preset
    (FC 0.16) that clamps a probe sitting near 0.44 — the bug this feature fixes.
    A `flat` series is dead-constant so its std-dev falls under the flatline floor.

    `constant_levels` ({depth_cm: value}) overrides both `depths_cm` and the wave:
    each depth gets its own dead-constant plateau. Per depth the std-dev is 0 (so
    build_quality reports all_depths_flatlined) while the sector calibration pools
    all shallow depths, so plateaus at different levels still yield a plausible
    FC-refill spread — the only way to reach the flatline gate with a candidate.
    """
    stamp = datetime.now(UTC).timestamp()
    user = User(
        email=f"autoapply-{stamp}@t.dev", name="AA", hashed_password="x", role="admin",
    )
    db.add(user)
    await db.flush()
    farm = Farm(name="AA Farm", owner_id=user.id, calibration_auto_apply=auto_apply)
    db.add(farm)
    await db.flush()
    plot = Plot(
        farm_id=farm.id, name="P", soil_texture="sandy_loam",
        field_capacity=0.16, wilting_point=0.07,
    )
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="AA Sector", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(
        sector_id=sector.id,
        external_id=f"aa-probe-{stamp}",
        last_reading_at=datetime.now(UTC) - timedelta(hours=last_reading_age_h),
    )
    db.add(probe)
    await db.flush()

    base = datetime.now(UTC) - timedelta(hours=59)
    levels = constant_levels or dict.fromkeys(depths_cm)
    for depth_cm, level in levels.items():
        depth = ProbeDepth(probe_id=probe.id, depth_cm=depth_cm, sensor_type="soil_moisture")
        db.add(depth)
        await db.flush()
        # Triangle wave across a realistic envelope with per-step moves < 0.03 so the
        # spike detector finds no irrigation events -> the envelope path is exercised
        # and the FC-refill spread clears CALIB_MIN_SPREAD_M3M3.
        lo, hi = vwc - 0.03, vwc + 0.015
        span = 0.0 if flat else hi - lo
        for i in range(60):
            phase = i % 24
            frac = phase / 12
            tri = frac if frac <= 1 else (2 - frac)
            v = level if level is not None else round(lo + span * tri, 4)
            db.add(ProbeReading(
                probe_depth_id=depth.id,
                timestamp=base + timedelta(hours=i),
                raw_value=v, calibrated_value=v,
                unit="vwc_m3m3", quality_flag="ok",
            ))
    await db.flush()
    return sector.id, farm.id


@pytest.mark.asyncio
async def test_quality_reports_fresh_probe_and_live_signal(db: AsyncSession):
    sector_id, _ = await _make_sector(db, last_reading_age_h=2.0)
    quality = await ProbeCalibrationService().build_quality(sector_id, db)
    assert quality.probe_hours_since_reading == pytest.approx(2.0, abs=0.2)
    assert quality.all_depths_flatlined is False
    await db.rollback()


@pytest.mark.asyncio
async def test_quality_flags_stale_probe(db: AsyncSession):
    sector_id, _ = await _make_sector(db, last_reading_age_h=100.0)
    quality = await ProbeCalibrationService().build_quality(sector_id, db)
    assert quality.probe_hours_since_reading == pytest.approx(100.0, abs=0.2)
    await db.rollback()


@pytest.mark.asyncio
async def test_quality_flags_flatline_when_all_depths_frozen(db: AsyncSession):
    sector_id, _ = await _make_sector(db, flat=True, depths_cm=(20, 40))
    quality = await ProbeCalibrationService().build_quality(sector_id, db)
    assert quality.all_depths_flatlined is True
    await db.rollback()


@pytest.mark.asyncio
async def test_one_flat_depth_among_live_ones_is_not_flatline(db: AsyncSession):
    """A frozen deep sensor below the root zone is normal, not a fault."""
    sector_id, _ = await _make_sector(db, depths_cm=(20,))
    # Add a second, dead-constant depth to the same probe.
    from sqlalchemy import select
    probe = (await db.execute(select(Probe).where(Probe.sector_id == sector_id))).scalar_one()
    deep = ProbeDepth(probe_id=probe.id, depth_cm=60, sensor_type="soil_moisture")
    db.add(deep)
    await db.flush()
    base = datetime.now(UTC) - timedelta(hours=59)
    for i in range(60):
        db.add(ProbeReading(
            probe_depth_id=deep.id, timestamp=base + timedelta(hours=i),
            raw_value=0.30, calibrated_value=0.30, unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.flush()

    quality = await ProbeCalibrationService().build_quality(sector_id, db)
    assert quality.all_depths_flatlined is False
    await db.rollback()


@pytest.mark.asyncio
async def test_quality_without_probe_reports_no_reading(db: AsyncSession):
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"npq-{stamp}@t.dev", name="NPQ", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name="NPQ", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="No probe", crop_type="almond")
    db.add(sector)
    await db.flush()

    quality = await ProbeCalibrationService().build_quality(sector.id, db)
    assert quality.probe_hours_since_reading is None
    assert quality.all_depths_flatlined is False
    await db.rollback()


async def _runs(db: AsyncSession, sector_id: str) -> list:
    return (await db.execute(
        select(ProbeCalibrationRun).where(ProbeCalibrationRun.sector_id == sector_id)
    )).scalars().all()


async def _projection(db: AsyncSession, sector_id: str):
    return (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalar_one_or_none()


@pytest.mark.asyncio
async def test_auto_apply_promotes_first_calibration_on_clamped_sector(db: AsyncSession):
    """Plot preset FC 0.16 vs probe near 0.44: the uncapped first apply must land."""
    sector_id, _ = await _make_sector(db, vwc=0.44)
    decision = await ProbeCalibrationService().compute_and_auto_apply(sector_id, db)

    assert decision.apply is True
    assert decision.reason == REASON_APPLIED

    runs = await _runs(db, sector_id)
    assert len(runs) == 1
    assert runs[0].status == "applied"
    assert runs[0].applied_at is not None
    assert runs[0].source == "scheduled"

    projection = await _projection(db, sector_id)
    assert projection is not None
    assert 0.43 <= projection.observed_fc <= 0.46
    await db.rollback()


@pytest.mark.asyncio
async def test_auto_apply_never_clears_manual_customization(db: AsyncSession):
    """THE critical invariant: the scheduler must not discard an agronomist's edit."""
    sector_id, _ = await _make_sector(db, vwc=0.44)
    # crop_type, mad, both root depths and stages are all non-null on this model.
    scp = SectorCropProfile(
        sector_id=sector_id,
        crop_type="almond",
        mad=0.45,
        root_depth_mature_m=0.9,
        root_depth_young_m=0.4,
        stages={},
        field_capacity=0.22,
        wilting_point=0.11,
        is_customized=True,
    )
    db.add(scp)
    await db.flush()

    decision = await ProbeCalibrationService().compute_and_auto_apply(sector_id, db)

    assert decision.apply is False
    assert decision.reason == REASON_MANUAL_OVERRIDE
    assert await _runs(db, sector_id) == []
    assert await _projection(db, sector_id) is None

    await db.refresh(scp)
    assert scp.is_customized is True
    assert scp.field_capacity == pytest.approx(0.22)
    await db.rollback()


@pytest.mark.asyncio
async def test_customized_profile_without_soil_fields_does_not_block(db: AsyncSession):
    """Gate 1 must key on the bounds the engine USES, not on the raw flag.

    `PUT /crop-profile` sets is_customized=True on ANY edit (e.g. bumping `mad`),
    but soil_bounds honours scp_override only when BOTH scp_fc and scp_pwp are set.
    With soil fields NULL the sector is still governed by the clamping plot preset,
    so blocking here would pin it at ~0% depletion forever — the exact bug this
    feature exists to fix.
    """
    sector_id, _ = await _make_sector(db, vwc=0.44)
    scp = SectorCropProfile(
        sector_id=sector_id,
        crop_type="almond",
        mad=0.45,
        root_depth_mature_m=0.9,
        root_depth_young_m=0.4,
        stages={},
        field_capacity=None,
        wilting_point=None,
        is_customized=True,
    )
    db.add(scp)
    await db.flush()

    before = await resolve_sector_soil_bounds(sector_id, db)
    assert before.source == "plot_preset"  # the flag does not govern soil bounds

    outcome = await ProbeCalibrationService().compute_and_auto_apply(sector_id, db)

    assert outcome.apply is True
    assert outcome.reason == REASON_APPLIED

    # THE invariant still holds: the auto path never clears the agronomist's flag.
    await db.refresh(scp)
    assert scp.is_customized is True
    await db.rollback()


@pytest.mark.asyncio
async def test_stale_prior_calibration_is_not_delta_capped(db: AsyncSession):
    """A calibration older than CALIB_MAX_AGE_DAYS must not deadlock the gate.

    soil_bounds IGNORES a stale calibration, so `before` is the clamping preset
    (0.16), not the old probe value. Capping the move against a preset the sector
    was never measured against blocks the sector permanently — and it can only get
    staler. The cap must apply only while the live bounds ARE probe-derived.
    """
    sector_id, _ = await _make_sector(db, vwc=0.44)
    db.add(ProbeCalibration(
        sector_id=sector_id,
        observed_fc=0.30,
        observed_refill=0.20,
        method="envelope",
        num_cycles=0,
        consistency=0.5,
        window_days=30,
        computed_at=datetime.now(UTC) - timedelta(days=100),
    ))
    await db.flush()

    before = await resolve_sector_soil_bounds(sector_id, db)
    assert before.source == "plot_preset"
    assert before.fc == pytest.approx(0.16)

    outcome = await ProbeCalibrationService().compute_and_auto_apply(sector_id, db)

    assert outcome.apply is True
    assert outcome.reason == REASON_APPLIED
    projection = await _projection(db, sector_id)
    assert projection.observed_fc > 0.40  # refreshed, no longer stale
    await db.rollback()


@pytest.mark.asyncio
async def test_blocked_run_is_not_recorded(db: AsyncSession):
    sector_id, _ = await _make_sector(db, last_reading_age_h=200.0)
    decision = await ProbeCalibrationService().compute_and_auto_apply(sector_id, db)

    assert decision.apply is False
    assert decision.reason == REASON_PROBE_STALE
    assert await _runs(db, sector_id) == []
    assert await _projection(db, sector_id) is None
    await db.rollback()


@pytest.mark.asyncio
async def test_flatlined_sector_yields_no_candidate(db: AsyncSession):
    """A dead-constant series never even reaches the flatline gate.

    compute_envelope_points returns fc == refill, so the spread is 0, which fails
    is_plausible_calibration -> compute_sector_calibration returns None -> gate 0.
    The flatline gate itself is covered by the pure policy test and by
    test_quality_flags_flatline_when_all_depths_frozen; this asserts the
    deterministic real-world path for a stuck sensor.
    """
    sector_id, _ = await _make_sector(db, flat=True)
    decision = await ProbeCalibrationService().compute_and_auto_apply(sector_id, db)

    assert decision.apply is False
    assert decision.reason == REASON_NO_CANDIDATE
    assert await _runs(db, sector_id) == []
    await db.rollback()


@pytest.mark.asyncio
async def test_flatline_gate_fires_end_to_end_when_a_candidate_exists(db: AsyncSession):
    """build_quality -> flatline gate, wired end to end.

    The trap: a single dead-constant series short-circuits to no_candidate (fc ==
    refill fails the plausibility spread), so it never proves the gate works. Here
    two shallow depths sit on plateaus 0.20 apart: each depth's std-dev is 0 (all
    depths flatlined) while the pooled shallow series gives fc 0.44 / refill 0.24 —
    a plausible candidate. So this reaches gate 3, not gate 0, and a wrong
    sensor_type / unit / quality_flag filter in build_quality would show up as
    REASON_APPLIED here.
    """
    sector_id, _ = await _make_sector(db, constant_levels={10: 0.24, 20: 0.44})
    svc = ProbeCalibrationService()

    # Precondition 1: a candidate genuinely exists (so gate 0 cannot fire).
    candidate = await svc._calibrator.compute_sector_calibration(sector_id, db)
    assert candidate is not None
    assert candidate.observed_fc == pytest.approx(0.44)

    # Precondition 2: the quality signal really is flatlined.
    quality = await svc.build_quality(sector_id, db)
    assert quality.all_depths_flatlined is True

    outcome = await svc.compute_and_auto_apply(sector_id, db)

    assert outcome.apply is False
    assert outcome.reason == REASON_FLATLINE  # not REASON_NO_CANDIDATE
    assert await _runs(db, sector_id) == []
    assert await _projection(db, sector_id) is None
    await db.rollback()


@pytest.mark.asyncio
async def test_no_candidate_when_sector_has_no_probe(db: AsyncSession):
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"nc-{stamp}@t.dev", name="NC", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name="NC", owner_id=user.id, calibration_auto_apply=True)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="No probe", crop_type="almond")
    db.add(sector)
    await db.flush()

    decision = await ProbeCalibrationService().compute_and_auto_apply(sector.id, db)
    assert decision.apply is False
    assert decision.reason == REASON_NO_CANDIDATE
    await db.rollback()


@pytest.mark.asyncio
async def test_auto_applied_run_is_audited_without_a_user(db: AsyncSession):
    """user_id IS NULL is how scheduler-applied bounds stay distinguishable
    from human-applied ones after the fact."""
    from app.models import AuditLog

    sector_id, _ = await _make_sector(db, vwc=0.44)
    await ProbeCalibrationService().compute_and_auto_apply(sector_id, db)

    entries = (await db.execute(
        select(AuditLog).where(
            AuditLog.action == "probe_calibration_auto_applied",
            AuditLog.entity_id == sector_id,
        )
    )).scalars().all()
    assert len(entries) == 1
    assert entries[0].user_id is None
    assert entries[0].entity_type == "sector"
    assert entries[0].after_data["method"] == "envelope"
    await db.rollback()


@pytest.mark.asyncio
async def test_second_apply_supersedes_the_first(db: AsyncSession):
    """The NEWEST run must be the live one.

    Asserting only sorted(statuses) == ["applied", "superseded"] would pass green
    on the inverted bug — superseding the new run and leaving the old bounds live —
    which would freeze bounds farm-wide. So identify the rows: the second run must
    be `applied` and the first `superseded`, and the projection must carry the
    second run's values.
    """
    sector_id, _ = await _make_sector(db, vwc=0.44)
    svc = ProbeCalibrationService()
    await svc.compute_and_auto_apply(sector_id, db)
    first = (await _runs(db, sector_id))[0]
    first_id = first.id

    # Same window, so the second candidate is within the delta cap and applies.
    await svc.compute_and_auto_apply(sector_id, db)

    runs = await _runs(db, sector_id)
    assert len(runs) == 2
    by_id = {r.id: r for r in runs}
    second = next(r for r in runs if r.id != first_id)
    assert second.computed_at >= by_id[first_id].computed_at

    assert second.status == "applied"
    assert second.applied_at is not None
    assert by_id[first_id].status == "superseded"

    projection = await _projection(db, sector_id)
    assert projection.observed_fc == pytest.approx(second.observed_fc)
    assert projection.computed_at == second.computed_at
    await db.rollback()


@pytest.mark.asyncio
async def test_sweep_applies_when_flag_on(db: AsyncSession):
    sector_id, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True)
    counts = await ProbeCalibrationService().compute_all_for_farm(
        farm_id, db, auto_apply=True
    )
    assert counts.applied == 1
    assert counts.candidates == 0
    assert counts.failed == 0

    runs = await _runs(db, sector_id)
    assert [r.status for r in runs] == ["applied"]
    await db.rollback()


@pytest.mark.asyncio
async def test_sweep_records_candidates_only_when_flag_off(db: AsyncSession):
    """The opt-out path must behave exactly as it does today."""
    sector_id, farm_id = await _make_sector(db, vwc=0.44, auto_apply=False)
    counts = await ProbeCalibrationService().compute_all_for_farm(
        farm_id, db, auto_apply=False
    )
    assert counts.candidates == 1
    assert counts.applied == 0

    runs = await _runs(db, sector_id)
    assert [r.status for r in runs] == ["candidate"]
    assert await _projection(db, sector_id) is None
    await db.rollback()


@pytest.mark.asyncio
async def test_one_failing_sector_does_not_abort_the_farm(db: AsyncSession):
    """Savepoint isolation: a GENUINE failed flush on sector A must not poison sector B.

    The patched method for the bad sector does not just raise a Python exception —
    it performs a real DB write (a ProbeCalibrationRun pointing at a nonexistent
    sector_id) and flushes it, which Postgres rejects with a foreign-key violation.
    That is exactly how the real bug manifests: `compute_and_auto_apply`/`apply_run`
    add() + flush() and a failed flush leaves the AsyncSession needing a rollback.
    Without `db.begin_nested()` around each sector, this failure would invalidate
    the whole session and the next sector's own flush would raise
    PendingRollbackError instead of succeeding — so this test does NOT rely on
    query ordering; it asserts the good sector still applies regardless of order,
    and separately proves the session itself is still usable afterward.
    """
    from uuid import uuid4

    good_id, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True)

    # A second sector on the same farm, built the same way.
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm_id))).scalar_one()
    bad = Sector(plot_id=plot.id, name="Boom", crop_type="almond")
    db.add(bad)
    await db.flush()
    bad_id = str(bad.id)

    svc = ProbeCalibrationService()
    original = svc.compute_and_auto_apply
    calls: list[str] = []

    async def flaky(sector_id, session):
        calls.append(sector_id)
        if sector_id == bad_id:
            # Real DBAPI failure: FK violation on a nonexistent sector_id, not a
            # Python-level raise. This is what actually aborts a Postgres
            # transaction and requires a rollback before the session is reusable.
            bogus_run = ProbeCalibrationRun(
                sector_id=str(uuid4()),
                observed_fc=0.30,
                observed_refill=0.20,
                method="envelope",
                num_cycles=0,
                consistency=0.0,
                window_days=30,
                computed_at=datetime.now(UTC),
                source="scheduled",
                status="candidate",
            )
            session.add(bogus_run)
            await session.flush()  # raises IntegrityError (FK violation) here
            raise AssertionError("unreachable: flush should have raised")
        return await original(sector_id, session)

    svc.compute_and_auto_apply = flaky
    counts = await svc.compute_all_for_farm(farm_id, db, auto_apply=True)

    assert counts.failed == 1
    assert counts.applied == 1
    assert set(calls) == {good_id, bad_id}

    # The good sector applied, regardless of which sector the sweep visited first.
    assert [r.status for r in await _runs(db, good_id)] == ["applied"]

    # The session itself must still be usable after the bad sector's aborted
    # flush — this is exactly the property a leaked PendingRollbackError breaks.
    still_usable = (await db.execute(
        select(Sector).where(Sector.id == good_id)
    )).scalar_one()
    assert still_usable.id == good_id

    await db.rollback()


@pytest.mark.asyncio
async def test_sweep_logs_one_line_per_applied_and_blocked_sector(db: AsyncSession):
    """Blocked runs leave no DB row, so the log is the only trace — per sector.

    Values must reach the log: an INFO with before/after FC and refill for the
    applied sector, a WARNING with both value pairs for the quality-blocked one.
    """
    applied_id, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True)
    # A second sector on the same farm whose probe is dead -> quality-blocked.
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm_id))).scalar_one()
    blocked = Sector(plot_id=plot.id, name="Stale", crop_type="almond")
    db.add(blocked)
    await db.flush()
    stale_probe = Probe(
        sector_id=blocked.id,
        external_id=f"aa-stale-{datetime.now(UTC).timestamp()}",
        last_reading_at=datetime.now(UTC) - timedelta(hours=200),
    )
    db.add(stale_probe)
    await db.flush()
    depth = ProbeDepth(probe_id=stale_probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    base = datetime.now(UTC) - timedelta(hours=59)
    for i in range(60):
        phase = i % 24
        frac = phase / 12
        tri = frac if frac <= 1 else (2 - frac)
        v = round(0.41 + 0.045 * tri, 4)
        db.add(ProbeReading(
            probe_depth_id=depth.id, timestamp=base + timedelta(hours=i),
            raw_value=v, calibrated_value=v, unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.flush()

    logger_name = "app.services.probe_calibration_service"
    with _capture(logger_name) as records:
        counts = await ProbeCalibrationService().compute_all_for_farm(
            farm_id, db, auto_apply=True
        )
    assert counts.applied == 1
    assert counts.skipped == 1

    infos = [r for r in records if r.levelno == logging.INFO and "applied" in r.getMessage()]
    assert len(infos) == 1
    applied_msg = infos[0].getMessage()
    assert str(applied_id) in applied_msg
    assert "0.16" in applied_msg              # before FC (the clamping preset)
    assert "0.07" in applied_msg              # before refill
    assert "fc" in applied_msg and "refill" in applied_msg

    warns = [r for r in records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    blocked_msg = warns[0].getMessage()
    assert str(blocked.id) in blocked_msg
    assert "probe_stale" in blocked_msg
    assert "0.16" in blocked_msg              # live pair
    assert "candidate fc=" in blocked_msg     # candidate pair
    await db.rollback()


@pytest.mark.asyncio
async def test_failed_savepoint_release_does_not_count_a_sector_twice(db: AsyncSession):
    """Counters/metrics/logs must run only AFTER the savepoint has released.

    A failure in RELEASE SAVEPOINT surfaces at `__aexit__`. With the increments
    inside the block the same sector counted as BOTH applied and error, and the
    summary log claimed applied=1 for bounds that may have been rolled back.
    """
    _, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True)
    real_begin_nested = db.begin_nested

    class _FailingRelease:
        def __init__(self, inner):
            self._inner = inner

        async def __aenter__(self):
            return await self._inner.__aenter__()

        async def __aexit__(self, *exc_info):
            await self._inner.__aexit__(*exc_info)
            raise RuntimeError("RELEASE SAVEPOINT failed")

    db.begin_nested = lambda: _FailingRelease(real_begin_nested())
    try:
        with _capture("app.services.probe_calibration_service") as records:
            counts = await ProbeCalibrationService().compute_all_for_farm(
                farm_id, db, auto_apply=True
            )
    finally:
        db.begin_nested = real_begin_nested

    assert counts.failed == 1
    assert counts.applied == 0          # never both
    assert counts.skipped == 0
    assert not [
        r for r in records
        if r.levelno == logging.INFO and "applied" in r.getMessage()
    ]
    await db.rollback()


@pytest.mark.asyncio
async def test_job_handler_reads_the_per_farm_flag(db: AsyncSession):
    """The job must pass each farm's own flag, not a global default."""
    from app.services.scheduler import _calibration_sweep_for_farm

    _, on_farm = await _make_sector(db, vwc=0.44, auto_apply=True)
    _, off_farm = await _make_sector(db, vwc=0.44, auto_apply=False)

    from sqlalchemy import select

    on = (await db.execute(select(Farm).where(Farm.id == on_farm))).scalar_one()
    off = (await db.execute(select(Farm).where(Farm.id == off_farm))).scalar_one()

    on_counts = await _calibration_sweep_for_farm(on, db)
    off_counts = await _calibration_sweep_for_farm(off, db)

    assert on_counts.applied == 1
    assert on_counts.candidates == 0
    assert off_counts.candidates == 1
    assert off_counts.applied == 0
    await db.rollback()
