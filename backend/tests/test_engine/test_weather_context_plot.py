"""Tests for build_weather_context plot-scoped resolution and representative-plot fallback.

The signature test checks the function accepts a plot_id kwarg (fast, no DB).
The DB-backed tests verify the three-tier resolution:
  (a) explicit plot_id  → returns that plot's rows
  (b) plot_id=None, no IS NULL rows → representative-plot fallback (not empty)
  (c) plot_id=None, IS NULL rows exist → returns farm-level rows unchanged
"""
import inspect
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.pipeline import build_weather_context
from app.models import Farm, Plot, User, WeatherObservation


# ---------------------------------------------------------------------------
# Signature test (no DB needed)
# ---------------------------------------------------------------------------

def test_build_weather_context_accepts_plot_id():
    assert "plot_id" in inspect.signature(build_weather_context).parameters


# ---------------------------------------------------------------------------
# DB session fixture (mirrors test_probe_calibration_db.py pattern)
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
# Helpers
# ---------------------------------------------------------------------------

async def _make_farm_with_plot(db: AsyncSession):
    """Create a user + farm + plot, flush, and return (farm, plot)."""
    stamp = datetime.now(UTC).timestamp()
    user = User(
        email=f"wctx-{stamp}@t.dev", name="WCtx", hashed_password="x", role="admin",
    )
    db.add(user)
    await db.flush()

    farm = Farm(name=f"WCtx Farm {stamp}", owner_id=user.id)
    db.add(farm)
    await db.flush()

    plot = Plot(farm_id=farm.id, name="P1", soil_texture="loam")
    db.add(plot)
    await db.flush()

    return farm, plot


def _obs(farm_id: str, plot_id: str | None, *, hours_ago: float = 1.0) -> WeatherObservation:
    """Build a minimal WeatherObservation row."""
    ts = datetime.now(UTC) - timedelta(hours=hours_ago)
    return WeatherObservation(
        farm_id=farm_id,
        plot_id=plot_id,
        timestamp=ts,
        temperature_max_c=28.0,
        temperature_min_c=12.0,
        temperature_mean_c=20.0,
        humidity_pct=55.0,
        wind_speed_ms=2.5,
        solar_radiation_mjm2=18.0,
        rainfall_mm=0.0,
        et0_mm=4.2,
        source="test",
    )


# ---------------------------------------------------------------------------
# (a) Explicit plot_id → returns that plot's observation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explicit_plot_id_returns_plot_obs(db: AsyncSession):
    """build_weather_context(farm, db, plot_id=P) must return the plot-scoped row."""
    farm, plot = await _make_farm_with_plot(db)

    # Insert only a plot-scoped row (no IS NULL row).
    db.add(_obs(farm.id, plot.id, hours_ago=2))
    await db.flush()

    ctx = await build_weather_context(farm.id, db, plot_id=plot.id)
    assert ctx.today.et0_mm == 4.2
    assert ctx.hours_since_observation is not None
    assert ctx.hours_since_observation < 24

    await db.rollback()


# ---------------------------------------------------------------------------
# (b) plot_id=None, no IS NULL rows → representative-plot fallback (not empty)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_representative_plot_fallback_when_no_farm_level_rows(db: AsyncSession):
    """For Innoliva-style farms (all rows plot-scoped, none IS NULL):
    build_weather_context(farm, db, plot_id=None) must fall back to the
    most-recent plot's rows and return non-empty weather, not empty."""
    farm, plot = await _make_farm_with_plot(db)

    # Only plot-scoped observations — no IS NULL rows at all.
    db.add(_obs(farm.id, plot.id, hours_ago=3))
    await db.flush()

    ctx = await build_weather_context(farm.id, db, plot_id=None)
    # Must not be empty — the representative-plot fallback should have found the row.
    assert ctx.today.et0_mm is not None
    assert ctx.hours_since_observation is not None

    await db.rollback()


# ---------------------------------------------------------------------------
# (c) plot_id=None, IS NULL rows exist → existing-farm behaviour unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_farm_level_rows_returned_unchanged(db: AsyncSession):
    """Existing farms with IS NULL weather rows must behave byte-for-byte unchanged:
    build_weather_context(farm, db, plot_id=None) returns the IS NULL row, not the
    plot-scoped one."""
    farm, plot = await _make_farm_with_plot(db)

    # Farm-level row (IS NULL) stored 1 h ago; plot-scoped row stored 2 h ago.
    # The IS NULL path should return the farm-level row (et0=5.0).
    farm_level_obs = _obs(farm.id, None, hours_ago=1)
    farm_level_obs.et0_mm = 5.0
    db.add(farm_level_obs)

    plot_obs = _obs(farm.id, plot.id, hours_ago=2)
    plot_obs.et0_mm = 4.2
    db.add(plot_obs)
    await db.flush()

    ctx = await build_weather_context(farm.id, db, plot_id=None)
    # Must get the IS NULL farm-level row, not the plot-scoped one.
    assert ctx.today.et0_mm == 5.0

    await db.rollback()
