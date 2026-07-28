"""DB-backed tests for calibration auto-apply.

Each test builds its own farm subtree with flush() and ends with rollback() —
never commit, and never touch the globally-seeded sector (that corrupts the
local dev DB and breaks test_context_loading::test_ctx_mad_in_range).
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import (
    Farm,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Sector,
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
