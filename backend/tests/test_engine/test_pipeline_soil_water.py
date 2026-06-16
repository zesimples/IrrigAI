"""E2E test: probe-less sector with an active flowmeter uses the soil-water model.

Requires the Docker database to be running with seed data loaded (make seed).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.pipeline import RecommendationPipeline
from app.models import (
    Farm,
    Flowmeter,
    FlowmeterReading,
    IrrigationEventDetected,
    Plot,
    Probe,
    Sector,
    WeatherObservation,
)

# ---------------------------------------------------------------------------
# Fixture — same pattern as test_pipeline.py
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probeless_flowmeter_sector_uses_water_balance_model(db: AsyncSession):
    """A probe-less sector with a flowmeter must get swc_source='water_balance_model'
    and a depletion that reflects measured irrigation/ET — not the static 30%."""
    today = date(2026, 6, 16)

    seed_farm_id = (await db.execute(
        select(Farm.id).where(Farm.name == "Herdade do Esporão")
    )).scalar_one()

    # order_by makes the sector choice deterministic regardless of seed insert order.
    sector = (await db.execute(
        select(Sector).join(Plot, Sector.plot_id == Plot.id)
        .where(Plot.farm_id == seed_farm_id).order_by(Sector.id)
    )).scalars().first()

    assert sector is not None, "Seed farm has no sectors — run: make seed"

    # Guarantee probe-less: delete any probes on the chosen sector.
    # Probe has cascade="all, delete-orphan" on depths which cascade into readings,
    # so deleting the Probe is sufficient.
    for p in (await db.execute(select(Probe).where(Probe.sector_id == sector.id))).scalars().all():
        await db.delete(p)
    await db.flush()

    # Attach an active flowmeter (Flowmeter.sector_id is UNIQUE — delete any existing first).
    for existing in (await db.execute(
        select(Flowmeter).where(Flowmeter.sector_id == sector.id)
    )).scalars().all():
        await db.delete(existing)
    await db.flush()

    fm = Flowmeter(
        sector_id=sector.id,
        external_device_id=999001,
        name="Test Flowmeter",
        is_active=True,
    )
    db.add(fm)
    await db.flush()

    # ~30 days of daily weather (et0=5), one early big-rain anchor, per-day flowmeter
    # readings (so no day is flagged offline), and a few irrigation events.
    for i in range(30):
        d = today - timedelta(days=29 - i)
        ts = datetime(d.year, d.month, d.day, 12, tzinfo=UTC)
        db.add(WeatherObservation(
            farm_id=seed_farm_id,
            timestamp=ts,
            rainfall_mm=40.0 if i == 0 else 0.0,
            et0_mm=5.0,
            source="test",
        ))
        db.add(FlowmeterReading(
            flowmeter_id=fm.id,
            timestamp=ts,
            value_m3_ha=0.0,
        ))

    # ~weekly irrigation events (days 19, 12, 5 before `today`), 3 mm net each.
    for i in (10, 17, 24):
        d = today - timedelta(days=29 - i)
        start_time = datetime(d.year, d.month, d.day, 6, tzinfo=UTC)
        end_time = datetime(d.year, d.month, d.day, 8, tzinfo=UTC)
        duration_minutes = (end_time - start_time).total_seconds() / 60
        db.add(IrrigationEventDetected(
            flowmeter_id=fm.id,
            sector_id=sector.id,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            total_m3_ha=30.0,
            peak_m3_ha=15.0,
            num_readings=8,
            date=d,
        ))
    await db.flush()

    rec = await RecommendationPipeline().run(sector.id, today, db, farm_id=seed_farm_id)

    assert rec.swc_source == "water_balance_model", (
        f"Expected swc_source='water_balance_model', got '{rec.swc_source}'"
    )
    assert rec.swc_model is not None, "swc_model dict must be set when using water_balance_model"

    # Static seed would pin depletion at exactly 30% of TAW; the model must differ.
    assert rec.taw_mm is not None and rec.taw_mm > 0, "taw_mm must be positive"
    assert rec.depletion_mm is not None, "depletion_mm must be set"
    assert abs((rec.depletion_mm / rec.taw_mm) - 0.30) > 0.02, (
        f"Depletion ratio {rec.depletion_mm / rec.taw_mm:.4f} is too close to static 30% seed; "
        f"the soil-water model should produce a different value"
    )
