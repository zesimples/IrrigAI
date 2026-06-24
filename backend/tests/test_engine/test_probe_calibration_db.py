"""DB-backed tests for probe-envelope calibration.

Requires the test Postgres (NullPool) — same db fixture style as test_pipeline_soil_water.py.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.auto_calibration import AutoCalibrationService
from app.engine.pipeline import build_sector_context
from app.models import (
    Farm,
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
