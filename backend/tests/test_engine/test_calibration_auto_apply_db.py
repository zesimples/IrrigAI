"""DB-backed tests for calibration auto-apply.

Each test builds its own farm subtree with flush() and ends with rollback() —
never commit, and never touch the globally-seeded sector (that corrupts the
local dev DB and breaks test_context_loading::test_ctx_mad_in_range).
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.calibration_policy import (
    REASON_APPLIED,
    REASON_MANUAL_OVERRIDE,
    REASON_NO_CANDIDATE,
    REASON_PROBE_STALE,
)
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
) -> tuple[str, str]:
    """Build Farm→Plot→Sector→Probe→ProbeDepth(s) + 60 hourly VWC readings.

    Returns (sector_id, farm_id). The plot carries the sandy_loam preset
    (FC 0.16) that clamps a probe sitting near 0.44 — the bug this feature fixes.
    A `flat` series is dead-constant so its std-dev falls under the flatline floor.
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
    for depth_cm in depths_cm:
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
            v = round(lo + span * tri, 4)
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
    sector_id, _ = await _make_sector(db, vwc=0.44)
    svc = ProbeCalibrationService()
    await svc.compute_and_auto_apply(sector_id, db)
    # Same window, so the second candidate is within the delta cap and applies.
    await svc.compute_and_auto_apply(sector_id, db)

    runs = await _runs(db, sector_id)
    assert len(runs) == 2
    statuses = sorted(r.status for r in runs)
    assert statuses == ["applied", "superseded"]
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
    """Savepoint isolation: a flush failure on sector A must not poison sector B."""
    good_id, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True)

    # A second sector on the same farm, built the same way.
    from sqlalchemy import select
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm_id))).scalar_one()
    bad = Sector(plot_id=plot.id, name="Boom", crop_type="almond")
    db.add(bad)
    await db.flush()

    svc = ProbeCalibrationService()
    original = svc.compute_and_auto_apply
    calls: list[str] = []

    async def flaky(sector_id, session):
        calls.append(sector_id)
        if sector_id == str(bad.id):
            raise RuntimeError("simulated flush failure")
        return await original(sector_id, session)

    svc.compute_and_auto_apply = flaky
    counts = await svc.compute_all_for_farm(farm_id, db, auto_apply=True)

    assert counts.failed == 1
    assert counts.applied == 1
    assert set(calls) == {good_id, str(bad.id)}
    assert [r.status for r in await _runs(db, good_id)] == ["applied"]
    await db.rollback()
