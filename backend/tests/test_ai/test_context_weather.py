"""AI weather context must use the engine's plot-scoped resolution rules."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.context_builder import get_weather_summary
from app.config import get_settings
from app.models import Farm, Plot, User, WeatherForecast, WeatherObservation


@pytest.fixture
async def db():
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _farm_with_plots(db: AsyncSession) -> tuple[Farm, Plot, Plot]:
    stamp = datetime.now(UTC).timestamp()
    user = User(
        email=f"ai-weather-{stamp}@test.dev",
        name="AI weather test",
        hashed_password="x",
    )
    db.add(user)
    await db.flush()
    farm = Farm(name=f"AI weather farm {stamp}", owner_id=user.id)
    db.add(farm)
    await db.flush()
    selected = Plot(farm_id=farm.id, name="Selected")
    fallback = Plot(farm_id=farm.id, name="Fallback")
    db.add_all([selected, fallback])
    await db.flush()
    return farm, selected, fallback


def _observation(farm_id: str, plot_id: str | None, et0_mm: float) -> WeatherObservation:
    return WeatherObservation(
        farm_id=farm_id,
        plot_id=plot_id,
        timestamp=datetime.now(UTC) - timedelta(hours=1),
        temperature_max_c=28.0,
        temperature_min_c=14.0,
        rainfall_mm=0.0,
        et0_mm=et0_mm,
        source="test",
    )


def _forecast(farm_id: str, plot_id: str | None, et0_mm: float) -> WeatherForecast:
    return WeatherForecast(
        farm_id=farm_id,
        plot_id=plot_id,
        forecast_date=date.today() + timedelta(days=1),
        issued_at=datetime.now(UTC),
        temperature_max_c=29.0,
        temperature_min_c=15.0,
        rainfall_mm=1.0,
        rainfall_probability_pct=20.0,
        et0_mm=et0_mm,
        source="test",
    )


@pytest.mark.asyncio
async def test_ai_weather_uses_only_selected_plot_rows(db: AsyncSession):
    farm, selected, _ = await _farm_with_plots(db)
    db.add_all(
        [
            _observation(farm.id, None, 8.1),
            _forecast(farm.id, None, 8.2),
            _observation(farm.id, selected.id, 4.1),
            _forecast(farm.id, selected.id, 4.2),
        ]
    )
    await db.flush()

    context = await get_weather_summary(farm.id, db, plot_id=selected.id)

    assert [row["et0_mm"] for row in context["recent_observations"]] == [4.1]
    assert [row["et0_mm"] for row in context["forecast"]] == [4.2]


@pytest.mark.asyncio
async def test_ai_weather_falls_back_to_farm_rows_for_uncovered_plot(db: AsyncSession):
    farm, _, uncovered = await _farm_with_plots(db)
    db.add_all([_observation(farm.id, None, 5.1), _forecast(farm.id, None, 5.2)])
    await db.flush()

    context = await get_weather_summary(farm.id, db, plot_id=uncovered.id)

    assert [row["et0_mm"] for row in context["recent_observations"]] == [5.1]
    assert [row["et0_mm"] for row in context["forecast"]] == [5.2]
