"""DB tests for IrrigationFingerprintService.

Seeds a sector with hourly VWC readings containing 3 clear irrigation rises,
persists matching DetectedWaterEvent rows, and asserts compute_and_save
learns the typical dose. Mirrors test_probe_calibration_db.py's fixtures.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import (
    DetectedWaterEvent,
    Farm,
    IrrigationFingerprint,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Sector,
    SectorCropProfile,
    User,
)
from app.services.irrigation_fingerprint_service import IrrigationFingerprintService


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def sector_with_probe_and_rises(db: AsyncSession):
    """Farm→Plot→Sector→Probe→ProbeDepth (2 depths) + hourly VWC readings over
    the last ~10 days, with 3 clear irrigation rises (+0.04 m3/m3 step over 1-2h)
    at known timestamps well inside the 25-day fingerprint window.

    Returns (sector, probe, farm, [event_time1, event_time2, event_time3]).
    """
    stamp = datetime.now(UTC).timestamp()
    user = User(
        email=f"fingerprint-{stamp}@t.dev",
        name="Fingerprint",
        hashed_password="x",
        role="admin",
    )
    db.add(user)
    await db.flush()
    farm = Farm(name="Fingerprint Farm", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(
        farm_id=farm.id,
        name="P",
        soil_texture="sandy_loam",
        field_capacity=0.40,
        wilting_point=0.18,
    )
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Fingerprint Sector", crop_type="olive")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id=f"fingerprint-probe-{stamp}")
    db.add(probe)
    await db.flush()

    depth_10 = ProbeDepth(probe_id=probe.id, depth_cm=10, sensor_type="soil_moisture")
    depth_20 = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add_all([depth_10, depth_20])
    await db.flush()

    # 10-day hourly series, well within the 25-day window. Baseline VWC drifts
    # down slowly between irrigations (a bit of ET-driven drying) and jumps up
    # sharply (+0.04) at each of the 3 known event times, over 2 hourly steps
    # (half the rise at +1h, the rest at +2h) so compute_event_dose sees a
    # clean baseline -> peak transition within its 3h/8h windows.
    now = datetime.now(UTC)
    n_hours = 24 * 10
    base_start = now - timedelta(hours=n_hours)

    event_times = [
        base_start + timedelta(hours=24),
        base_start + timedelta(hours=96),
        base_start + timedelta(hours=168),
    ]

    baseline = 0.28
    rise = 0.04
    depths = {10: depth_10.id, 20: depth_20.id}

    for _depth_cm, depth_id in depths.items():
        level = baseline
        for i in range(n_hours + 1):
            ts = base_start + timedelta(hours=i)
            # Slow drying drift between events, reset after each irrigation rise.
            for event_ts in event_times:
                hours_since_event = (ts - event_ts).total_seconds() / 3600.0
                if hours_since_event in (1.0, 2.0):
                    level += rise * 0.5
            value = round(level, 4)
            db.add(
                ProbeReading(
                    probe_depth_id=depth_id,
                    timestamp=ts,
                    raw_value=value,
                    calibrated_value=None,
                    unit="vwc_m3m3",
                    quality_flag="ok",
                )
            )
            level = max(baseline - 0.02, level - 0.0005)  # gentle drying drift
    await db.flush()

    return sector, probe, farm, event_times


async def _seed_event(
    db, probe_id, sector_id, farm_id, ts, *, kind="irrigation", status="active", confidence="high"
):
    db.add(
        DetectedWaterEvent(
            probe_id=probe_id,
            sector_id=sector_id,
            farm_id=farm_id,
            timestamp=ts,
            kind=kind,
            confidence=confidence,
            status=status,
            depths_cm=[10, 20],
            delta_vwc=0.05,
            message="",
        )
    )
    await db.flush()


async def test_compute_and_save_learns_from_three_events(db, sector_with_probe_and_rises):
    """sector_with_probe_and_rises: fixture seeding 3 VWC rise cycles at known times."""
    sector, probe, farm, event_times = sector_with_probe_and_rises
    for ts in event_times:
        await _seed_event(db, probe.id, sector.id, farm.id, ts)

    svc = IrrigationFingerprintService()
    row = await svc.compute_and_save(str(sector.id), db)

    assert row is not None
    assert row.n_events == 3
    assert row.typical_event_net_mm > 0
    assert row.window_days == 25

    # Idempotent upsert: second run updates the same row
    row2 = await svc.compute_and_save(str(sector.id), db)
    ids = (
        (
            await db.execute(
                select(IrrigationFingerprint).where(
                    IrrigationFingerprint.sector_id == str(sector.id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ids) == 1
    assert row2.id == row.id
    await db.rollback()


async def test_rejected_and_rain_events_excluded(db, sector_with_probe_and_rises):
    sector, probe, farm, event_times = sector_with_probe_and_rises
    await _seed_event(db, probe.id, sector.id, farm.id, event_times[0], status="rejected")
    await _seed_event(db, probe.id, sector.id, farm.id, event_times[1], kind="rain")
    await _seed_event(db, probe.id, sector.id, farm.id, event_times[2])

    svc = IrrigationFingerprintService()
    assert await svc.compute_and_save(str(sector.id), db) is None  # only 1 usable < 3
    await db.rollback()


async def test_compute_and_save_with_crop_profile_does_not_raise(db, sector_with_probe_and_rises):
    """Regression: SectorCropProfile has root_depth_mature_m/root_depth_young_m,
    not root_depth_m. compute_and_save must not raise AttributeError when a
    sector has a crop profile row attached.

    root_depth_mature_m=0.5 (50cm) is deeper than both fixture sensors
    (10cm, 20cm), so it doesn't actually cap either layer — the assertion
    here is simply that compute_and_save succeeds and returns a row.
    """
    sector, probe, farm, event_times = sector_with_probe_and_rises
    for ts in event_times:
        await _seed_event(db, probe.id, sector.id, farm.id, ts)

    scp = SectorCropProfile(
        sector_id=sector.id,
        crop_type="olive",
        mad=0.5,
        root_depth_mature_m=0.5,
        root_depth_young_m=0.3,
        stages=[],
    )
    db.add(scp)
    await db.flush()

    svc = IrrigationFingerprintService()
    row = await svc.compute_and_save(str(sector.id), db)

    assert row is not None
    assert row.n_events == 3
    await db.rollback()


async def test_low_confidence_unreviewed_events_excluded(db, sector_with_probe_and_rises):
    sector, probe, farm, event_times = sector_with_probe_and_rises
    for ts in event_times:
        await _seed_event(db, probe.id, sector.id, farm.id, ts, confidence="low")

    svc = IrrigationFingerprintService()
    assert await svc.compute_and_save(str(sector.id), db) is None
    await db.rollback()
