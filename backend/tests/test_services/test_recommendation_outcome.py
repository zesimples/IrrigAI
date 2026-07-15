from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Farm, IrrigationEvent, Plot, Recommendation, Sector, User
from app.services.recommendation_outcome_service import evaluate_recommendation


@pytest.fixture
async def db():
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _sector(db: AsyncSession, suffix: str) -> Sector:
    user = User(
        email=f"outcome-{suffix}@test.dev",
        name="Outcome",
        hashed_password="x",
    )
    db.add(user)
    await db.flush()
    farm = Farm(name="Outcome Farm", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="S", crop_type="olive")
    db.add(sector)
    await db.flush()
    return sector


@pytest.mark.asyncio
async def test_outcome_matches_actual_dose_and_computes_error(db: AsyncSession):
    sector = await _sector(db, "executed")
    generated = datetime.now(UTC) - timedelta(hours=4)
    recommendation = Recommendation(
        sector_id=sector.id,
        generated_at=generated,
        target_date=generated.date(),
        action="irrigate",
        irrigation_depth_mm=10.0,
        confidence_score=0.8,
        confidence_level="high",
        is_accepted=True,
        engine_version="test",
        inputs_snapshot={},
        computation_log={},
    )
    db.add(recommendation)
    await db.flush()
    db.add(IrrigationEvent(
        sector_id=sector.id,
        recommendation_id=recommendation.id,
        start_time=generated + timedelta(hours=1),
        applied_mm=12.0,
        source="manual_log",
    ))
    await db.flush()

    outcome = await evaluate_recommendation(recommendation, db)

    assert outcome is not None
    assert outcome.status == "executed"
    assert outcome.actual_applied_mm == 12.0
    assert outcome.dose_error_mm == 2.0
    assert outcome.dose_error_pct == 20.0


@pytest.mark.asyncio
async def test_outcome_records_followed_skip_after_window(db: AsyncSession):
    sector = await _sector(db, "skip")
    generated = datetime.now(UTC) - timedelta(hours=40)
    recommendation = Recommendation(
        sector_id=sector.id,
        generated_at=generated,
        target_date=generated.date(),
        action="skip",
        irrigation_depth_mm=None,
        confidence_score=0.8,
        confidence_level="high",
        is_accepted=True,
        engine_version="test",
        inputs_snapshot={},
        computation_log={},
    )
    db.add(recommendation)
    await db.flush()

    outcome = await evaluate_recommendation(recommendation, db)

    assert outcome is not None
    assert outcome.status == "followed_skip"
    assert outcome.actual_applied_mm == 0.0
