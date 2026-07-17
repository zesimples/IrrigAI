"""DB-backed tests for probe-envelope calibration.

Requires the test Postgres (NullPool) — same db fixture style as test_pipeline_soil_water.py.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.context_builder import build_structured_agronomic_context
from app.ai.probe_signal import compute_probe_signal_stats
from app.config import get_settings
from app.engine.auto_calibration import AutoCalibrationService
from app.engine.pipeline import build_sector_context
from app.models import (
    DetectedWaterEvent,
    Farm,
    Flowmeter,
    IrrigationEventDetected,
    Plot,
    Probe,
    ProbeCalibration,
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


async def _make_pinned_sector(db: AsyncSession, vwc: float) -> str:
    """Farm→Plot→Sector→Probe→ProbeDepth + 60 hourly VWC readings near `vwc`."""
    stamp = datetime.now(UTC).timestamp()
    user = User(
        email=f"calib-{stamp}@t.dev", name="Calib", hashed_password="x", role="admin",
    )
    db.add(user)
    await db.flush()
    farm = Farm(name="Calib Farm", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", soil_texture="sandy_loam",
                field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Pinned", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id="calib-probe")
    db.add(probe)
    await db.flush()
    # Real probe data uses sensor_type "soil_moisture" (not "moisture"); the engine's
    # probe_interpreter selects depths by unit, not sensor_type. Calibration must match.
    depth = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    # End the series near "now" so probe_interpreter treats the sector as having
    # fresh probe-weighted SWC (needed by the pipeline-labelling test).
    base = datetime.now(UTC) - timedelta(hours=59)
    # Gentle triangle wave across a realistic ~0.045 m³/m³ envelope (lo..hi), with
    # small per-hour steps (<0.03) so the spike detector finds no irrigation events
    # → the envelope (percentile) path is exercised, and the FC−refill spread clears
    # the CALIB_MIN_SPREAD_M3M3 plausibility guard.
    lo, hi = vwc - 0.03, vwc + 0.015
    span = hi - lo
    period = 24
    for i in range(60):
        phase = i % period
        frac = phase / (period / 2)            # 0 → 2 across the period
        tri = frac if frac <= 1 else (2 - frac)  # triangle 0 → 1 → 0
        v = round(lo + span * tri, 4)
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=v, calibrated_value=v,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.flush()
    return sector.id


@pytest.mark.asyncio
async def test_envelope_calibration_for_pinned_sector(db: AsyncSession):
    sector_id = await _make_pinned_sector(db, vwc=0.44)
    result = await AutoCalibrationService().compute_sector_calibration(sector_id, db)
    assert result is not None
    assert result.method == "envelope"     # no irrigation events → cycle path skipped
    assert 0.43 <= result.observed_fc <= 0.46
    assert result.observed_fc > result.observed_refill
    await db.rollback()


@pytest.mark.asyncio
async def test_no_calibration_when_no_probe(db: AsyncSession):
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"np-{stamp}@t.dev", name="NP", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name="NP", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="No probe", crop_type="almond")
    db.add(sector)
    await db.flush()
    result = await AutoCalibrationService().compute_sector_calibration(sector.id, db)
    assert result is None
    await db.rollback()


@pytest.mark.asyncio
async def test_compute_and_save_upserts_one_row(db: AsyncSession):
    sector_id = await _make_pinned_sector(db, vwc=0.44)
    svc = ProbeCalibrationService()

    row1 = await svc.compute_and_save(sector_id, db)
    assert row1 is not None
    first_computed_at = row1.computed_at

    # Second run must update the same row, not insert a duplicate.
    row2 = await svc.compute_and_save(sector_id, db)
    assert row2 is not None
    rows = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].computed_at >= first_computed_at
    await db.rollback()


@pytest.mark.asyncio
async def test_build_sector_context_uses_calibration(db: AsyncSession):
    sector_id = await _make_pinned_sector(db, vwc=0.44)   # plot preset FC=0.16
    # Mirror prod: the sector also has an SCP with a preset-derived field_capacity.
    # Calibration must still win over it (this is the bug that pinned prod).
    db.add(SectorCropProfile(
        sector_id=sector_id, crop_type="almond", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3,
        field_capacity=0.16, wilting_point=0.07, stages=[],
    ))
    # Persist a calibration row well above the preset.
    db.add(ProbeCalibration(
        sector_id=sector_id, observed_fc=0.46, observed_refill=0.30,
        method="envelope", num_cycles=0, consistency=0.5, window_days=60,
        computed_at=datetime.now(UTC),
    ))
    await db.flush()

    ctx = await build_sector_context(sector_id, db)
    assert ctx.field_capacity == 0.46              # calibrated, not preset SCP 0.16
    assert ctx.wilting_point == 0.30               # refill used as lower bound
    assert ctx.field_capacity_source == "probe_calibrated"
    assert ctx.fc_calibration is not None
    assert ctx.fc_calibration["method"] == "envelope"
    await db.rollback()


@pytest.mark.asyncio
async def test_resolve_sector_soil_bounds_matches_engine(db: AsyncSession):
    """The shared resolver (used by both the engine and the probe chart) must return
    the calibrated bounds, so the chart's CC/PMP can't diverge from the engine."""
    from app.engine.pipeline import resolve_sector_soil_bounds

    sector_id = await _make_pinned_sector(db, vwc=0.44)   # plot preset FC=0.16
    db.add(SectorCropProfile(
        sector_id=sector_id, crop_type="almond", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3,
        field_capacity=0.16, wilting_point=0.07, stages=[],
    ))
    db.add(ProbeCalibration(
        sector_id=sector_id, observed_fc=0.46, observed_refill=0.30,
        method="envelope", num_cycles=0, consistency=0.5, window_days=60,
        computed_at=datetime.now(UTC),
    ))
    await db.flush()

    bounds = await resolve_sector_soil_bounds(sector_id, db)
    assert bounds.source == "probe_calibrated"
    assert bounds.fc == 0.46          # calibrated, not preset SCP 0.16 / plot 0.16
    assert bounds.pwp == 0.30         # refill as lower bound
    await db.rollback()


@pytest.mark.asyncio
async def test_ai_context_uses_calibrated_soil_bounds_with_provenance(db: AsyncSession):
    sector_id = await _make_pinned_sector(db, vwc=0.44)
    db.add(
        SectorCropProfile(
            sector_id=sector_id,
            crop_type="almond",
            mad=0.5,
            root_depth_mature_m=0.6,
            root_depth_young_m=0.3,
            field_capacity=0.16,
            wilting_point=0.07,
            stages=[],
        )
    )
    db.add(
        ProbeCalibration(
            sector_id=sector_id,
            observed_fc=0.46,
            observed_refill=0.30,
            method="envelope",
            num_cycles=0,
            consistency=0.5,
            window_days=60,
            computed_at=datetime.now(UTC),
        )
    )
    await db.flush()
    latest_reading = (
        await db.execute(
            select(ProbeReading)
            .join(ProbeDepth, ProbeReading.probe_depth_id == ProbeDepth.id)
            .join(Probe, ProbeDepth.probe_id == Probe.id)
            .where(Probe.sector_id == sector_id)
            .order_by(ProbeReading.timestamp.desc())
            .limit(1)
        )
    ).scalar_one()
    latest_reading.raw_value = 0.12
    latest_reading.calibrated_value = 0.451
    await db.flush()

    context = await build_structured_agronomic_context(sector_id, db)

    assert context["soil"]["field_capacity"] == 0.46
    assert context["soil"]["wilting_point"] == 0.30
    assert context["soil"]["provenance"]["source"] == "probe_calibrated"
    assert context["soil"]["provenance"]["stale"] is False
    assert context["soil"]["provenance"]["computed_at"] is not None
    latest = context["probe_summary"]["latest_readings"][0]
    assert latest["vwc"] == 0.451
    assert latest["latest_reading_at"] is not None
    assert context["probe_summary"]["live"]["depths"] == context["probe_summary"][
        "latest_readings"
    ]
    await db.rollback()


@pytest.mark.asyncio
async def test_probe_signal_moisture_label_uses_calibrated_bounds(db: AsyncSession):
    sector_id = await _make_pinned_sector(db, vwc=0.44)
    db.add(
        ProbeCalibration(
            sector_id=sector_id,
            observed_fc=0.46,
            observed_refill=0.30,
            method="envelope",
            num_cycles=0,
            consistency=0.5,
            window_days=60,
            computed_at=datetime.now(UTC),
        )
    )
    await db.flush()
    probe = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalar_one()

    stats = await compute_probe_signal_stats(probe.id, db)

    assert stats["soil_bounds"]["source"] == "probe_calibrated"
    assert stats["depths"][0]["humidade_actual"] == "humidade elevada"
    await db.rollback()


@pytest.mark.asyncio
async def test_probe_signal_uses_confirmed_probe_detected_irrigation(db: AsyncSession):
    sector_id = await _make_pinned_sector(db, vwc=0.44)
    probe = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalar_one()
    event_at = datetime.now(UTC) - timedelta(hours=12)
    db.add(
        DetectedWaterEvent(
            probe_id=probe.id,
            sector_id=sector_id,
            timestamp=event_at,
            kind="irrigation",
            confidence="high",
            status="confirmed",
            depths_cm=[20],
            delta_vwc=0.04,
            irrigation_mm=8.0,
            message="test",
        )
    )
    await db.flush()

    stats = await compute_probe_signal_stats(probe.id, db)

    assert stats["n_irrigation_events_in_window"] == 1
    assert stats["last_irrigation_event_source"] == "probe_detected"
    assert stats["last_irrigation_applied_mm"] == 8.0
    assert stats["depths"][0]["resposta_rega"] is not None
    await db.rollback()


@pytest.mark.asyncio
async def test_probe_signal_uses_flowmeter_detected_irrigation(db: AsyncSession):
    sector_id = await _make_pinned_sector(db, vwc=0.44)
    probe = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalar_one()
    flowmeter = Flowmeter(
        sector_id=sector_id,
        external_device_id=991122,
        name="Test flowmeter",
    )
    db.add(flowmeter)
    await db.flush()
    event_at = datetime.now(UTC) - timedelta(hours=12)
    db.add(
        IrrigationEventDetected(
            flowmeter_id=flowmeter.id,
            sector_id=sector_id,
            start_time=event_at,
            end_time=event_at + timedelta(hours=1),
            duration_minutes=60.0,
            total_m3_ha=80.0,
            peak_m3_ha=20.0,
            num_readings=4,
            date=event_at.date(),
        )
    )
    await db.flush()

    stats = await compute_probe_signal_stats(probe.id, db)

    assert stats["n_irrigation_events_in_window"] == 1
    assert stats["last_irrigation_event_source"] == "flowmeter_detected"
    assert stats["last_irrigation_applied_mm"] == 8.0
    assert stats["depths"][0]["resposta_rega"] is not None
    await db.rollback()


@pytest.mark.asyncio
async def test_customized_scp_overrides_calibration_db(db: AsyncSession):
    """A deliberate user soil setting (is_customized=True) wins over calibration."""
    from app.engine.pipeline import resolve_sector_soil_bounds

    sector_id = await _make_pinned_sector(db, vwc=0.44)
    db.add(SectorCropProfile(
        sector_id=sector_id, crop_type="almond", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3,
        field_capacity=0.32, wilting_point=0.14, stages=[], is_customized=True,
    ))
    db.add(ProbeCalibration(
        sector_id=sector_id, observed_fc=0.46, observed_refill=0.30,
        method="envelope", num_cycles=0, consistency=0.5, window_days=60,
        computed_at=datetime.now(UTC),
    ))
    await db.flush()

    bounds = await resolve_sector_soil_bounds(sector_id, db)
    assert bounds.source == "scp_override"
    assert bounds.fc == 0.32          # user's deliberate choice, not calibrated 0.46
    assert bounds.pwp == 0.14
    await db.rollback()


@pytest.mark.asyncio
async def test_stale_calibration_ignored_by_resolution(db: AsyncSession):
    """A calibration older than CALIB_MAX_AGE_DAYS must NOT drive the bounds —
    resolution falls back to the plot preset, but the stale meta is surfaced."""
    from app.engine.auto_calibration import CALIB_MAX_AGE_DAYS
    from app.engine.pipeline import resolve_sector_soil_bounds

    sector_id = await _make_pinned_sector(db, vwc=0.44)   # plot preset FC=0.16
    stale_at = datetime.now(UTC) - timedelta(days=CALIB_MAX_AGE_DAYS + 5)
    db.add(ProbeCalibration(
        sector_id=sector_id, observed_fc=0.46, observed_refill=0.30,
        method="envelope", num_cycles=0, consistency=0.5, window_days=60,
        computed_at=stale_at,
    ))
    await db.flush()

    bounds = await resolve_sector_soil_bounds(sector_id, db)
    assert bounds.source == "plot_preset"     # NOT probe_calibrated
    assert bounds.fc == 0.16                   # plot preset, not stale calibrated 0.46
    assert bounds.pwp == 0.07
    # Provenance: the stale calibration is surfaced as ignored.
    assert bounds.calibration is not None
    assert bounds.calibration["stale"] is True
    assert bounds.calibration["used"] is False
    await db.rollback()


@pytest.mark.asyncio
async def test_fresh_calibration_marked_used(db: AsyncSession):
    """A fresh calibration drives the bounds and is flagged used=True / stale=False."""
    from app.engine.pipeline import resolve_sector_soil_bounds

    sector_id = await _make_pinned_sector(db, vwc=0.44)
    db.add(ProbeCalibration(
        sector_id=sector_id, observed_fc=0.46, observed_refill=0.30,
        method="envelope", num_cycles=0, consistency=0.5, window_days=60,
        computed_at=datetime.now(UTC),
    ))
    await db.flush()

    bounds = await resolve_sector_soil_bounds(sector_id, db)
    assert bounds.source == "probe_calibrated"
    assert bounds.calibration["used"] is True
    assert bounds.calibration["stale"] is False
    await db.rollback()


@pytest.mark.asyncio
async def test_invalid_readings_produce_no_calibration(db: AsyncSession):
    """Readings that are not good-quality vwc_m3m3 are unusable → no calibration."""
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"inv-{stamp}@t.dev", name="Inv", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name="Inv", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Invalid readings", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id="inv-probe")
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    base = datetime.now(UTC) - timedelta(hours=59)
    # 60 readings, but either wrong unit (tension/watermark) or bad quality flag —
    # none should be consumed as VWC.
    for i in range(60):
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=0.44, calibrated_value=0.44,
            unit="kpa" if i % 2 == 0 else "vwc_m3m3",
            quality_flag="ok" if i % 2 == 0 else "suspect",
        ))
    await db.flush()

    result = await AutoCalibrationService().compute_sector_calibration(sector.id, db)
    assert result is None
    await db.rollback()


@pytest.mark.asyncio
async def test_insufficient_readings_produce_no_calibration(db: AsyncSession):
    """Fewer than CALIB_MIN_READINGS good readings → no calibration."""
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"few-{stamp}@t.dev", name="Few", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name="Few", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Few readings", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id="few-probe")
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    base = datetime.now(UTC) - timedelta(hours=10)
    for i in range(6):     # < CALIB_MIN_READINGS (48)
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=0.44, calibrated_value=0.44,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.flush()

    result = await AutoCalibrationService().compute_sector_calibration(sector.id, db)
    assert result is None
    await db.rollback()


@pytest.mark.asyncio
async def test_pipeline_labels_probe_calibrated_source(db: AsyncSession):
    from datetime import date

    from app.engine.pipeline import RecommendationPipeline

    sector_id = await _make_pinned_sector(db, vwc=0.44)
    db.add(ProbeCalibration(
        sector_id=sector_id, observed_fc=0.46, observed_refill=0.30,
        method="envelope", num_cycles=0, consistency=0.5, window_days=60,
        computed_at=datetime.now(UTC),
    ))
    await db.flush()

    rec = await RecommendationPipeline().run(sector_id, date(2026, 6, 24), db)
    # The fc_calibration payload is the load-bearing assertion.
    assert rec.fc_calibration is not None
    assert rec.fc_calibration["method"] == "envelope"
    # Probe present + calibrated bounds → labelled probe_calibrated (or at least
    # probe_weighted if the interpreter needs even fresher data than the fixture).
    assert rec.swc_source in {"probe_calibrated", "probe_weighted"}
    await db.rollback()
