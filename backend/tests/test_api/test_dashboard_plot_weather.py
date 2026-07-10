"""Dashboard per-plot weather (Boletim card per Polo).

The dashboard response must expose `weather_by_plot` so the frontend can show
each plot's own station data when the farm has plot-scoped weather (Innoliva),
while farms with a single farm-level station (Esporão/Conqueiros) get an empty
map and behave exactly as before.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Farm, Plot, User, WeatherForecast, WeatherObservation
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"


def _obs(farm_id: str, plot_id: str | None, *, et0: float, hours_ago: float = 1.0):
    return WeatherObservation(
        farm_id=farm_id,
        plot_id=plot_id,
        timestamp=datetime.now(UTC) - timedelta(hours=hours_ago),
        temperature_max_c=20.0 + et0,
        temperature_min_c=10.0,
        temperature_mean_c=15.0 + et0 / 2,
        humidity_pct=50.0,
        wind_speed_ms=2.0,
        rainfall_mm=0.0,
        et0_mm=et0,
        source="test",
    )


def _fct(farm_id: str, plot_id: str | None, *, rain: float, days_ahead: int = 0,
         tmax: float | None = None, et0: float | None = None):
    return WeatherForecast(
        farm_id=farm_id,
        plot_id=plot_id,
        forecast_date=date.today() + timedelta(days=days_ahead),
        issued_at=datetime.now(UTC),
        temperature_max_c=tmax,
        temperature_min_c=9.0 if tmax is not None else None,
        rainfall_mm=rain,
        rainfall_probability_pct=40.0,
        et0_mm=et0,
        source="test",
    )


@pytest.fixture
async def plot_weather_farm(db: AsyncSession):
    """Farm owned by the API test user with three plots:

    - plot A: own observations + forecast (et0 4.2, rain 48h = 3.0)
    - plot B: own observations + forecast (et0 6.6, rain 48h = 0.0)
    - plot C: forecast only (Conceição pattern — no iMetos)
    No farm-level (plot_id IS NULL) weather rows at all.
    """
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()

    stamp = datetime.now(UTC).timestamp()
    farm = Farm(name=f"PlotWeather Farm {stamp}", owner_id=owner.id)
    db.add(farm)
    await db.flush()

    plot_a = Plot(farm_id=farm.id, name="Polo A", soil_texture="loam")
    plot_b = Plot(farm_id=farm.id, name="Polo B", soil_texture="loam")
    plot_c = Plot(farm_id=farm.id, name="Polo C", soil_texture="loam")
    db.add_all([plot_a, plot_b, plot_c])
    await db.flush()

    db.add_all([
        _obs(farm.id, plot_a.id, et0=4.2),
        _obs(farm.id, plot_b.id, et0=6.6),
        _fct(farm.id, plot_a.id, rain=1.0, days_ahead=0),
        _fct(farm.id, plot_a.id, rain=2.0, days_ahead=1),
        _fct(farm.id, plot_b.id, rain=0.0, days_ahead=0),
        _fct(farm.id, plot_b.id, rain=0.0, days_ahead=1),
        # forecast-only plot: values must surface from the forecast rows
        _fct(farm.id, plot_c.id, rain=5.5, days_ahead=0, tmax=31.0, et0=7.1),
        _fct(farm.id, plot_c.id, rain=0.0, days_ahead=1, tmax=30.0, et0=6.9),
    ])
    await db.commit()

    yield {
        "farm_id": farm.id,
        "plot_a": plot_a.id,
        "plot_b": plot_b.id,
        "plot_c": plot_c.id,
    }

    await delete_farm_subtree(db, farm.id)


@pytest.fixture
async def seed_farm_id(db: AsyncSession) -> str:
    farm = (
        await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))
    ).scalar_one()
    return farm.id


class TestDashboardPlotWeather:
    async def test_farm_level_farm_has_empty_weather_by_plot(
        self, client: AsyncClient, seed_farm_id: str
    ):
        """Farms with one farm-level station (plot_id IS NULL rows) expose an
        empty map — same single-Boletim behaviour as today."""
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "weather_by_plot" in data
        assert data["weather_by_plot"] == {}

    async def test_plot_scoped_weather_keyed_by_plot_id(
        self, client: AsyncClient, plot_weather_farm: dict
    ):
        resp = await client.get(f"/api/v1/farms/{plot_weather_farm['farm_id']}/dashboard")
        assert resp.status_code == 200
        by_plot = resp.json()["weather_by_plot"]

        a = by_plot[plot_weather_farm["plot_a"]]
        b = by_plot[plot_weather_farm["plot_b"]]
        assert a["et0_mm"] == 4.2
        assert b["et0_mm"] == 6.6
        assert a["forecast_rain_next_48h_mm"] == 3.0
        assert b["forecast_rain_next_48h_mm"] == 0.0

    async def test_forecast_only_plot_fills_from_forecast(
        self, client: AsyncClient, plot_weather_farm: dict
    ):
        """A plot with no station (Conceição) must show its own forecast values,
        not another plot's observations."""
        resp = await client.get(f"/api/v1/farms/{plot_weather_farm['farm_id']}/dashboard")
        c = resp.json()["weather_by_plot"][plot_weather_farm["plot_c"]]
        assert c["et0_mm"] == 7.1
        assert c["temperature_max_c"] == 31.0
        assert c["forecast_rain_next_48h_mm"] == 5.5

    async def test_weather_today_still_populated_for_plot_scoped_farm(
        self, client: AsyncClient, plot_weather_farm: dict
    ):
        """Farm-level weather_today must stay non-empty (representative plot)
        for farms whose rows are all plot-scoped — the home page uses it."""
        resp = await client.get(f"/api/v1/farms/{plot_weather_farm['farm_id']}/dashboard")
        w = resp.json()["weather_today"]
        assert w["et0_mm"] is not None
