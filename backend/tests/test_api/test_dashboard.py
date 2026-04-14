"""API tests for the dashboard endpoint."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Farm


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_farm_id(db: AsyncSession) -> str:
    farm = (await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))).scalar_one()
    return farm.id


class TestDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_returns_200(self, client: AsyncClient, seed_farm_id: str):
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_dashboard_structure(self, client: AsyncClient, seed_farm_id: str):
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        data = resp.json()
        assert "farm" in data
        assert "date" in data
        assert "weather_today" in data
        assert "sectors_summary" in data
        assert "active_alerts_count" in data
        assert "missing_data_prompts" in data

    @pytest.mark.asyncio
    async def test_dashboard_has_all_sectors(self, client: AsyncClient, seed_farm_id: str):
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        data = resp.json()
        assert len(data["sectors_summary"]) >= 4, (
            f"Expected ≥4 sectors, got {len(data['sectors_summary'])}"
        )

    @pytest.mark.asyncio
    async def test_sector_summaries_have_required_fields(self, client: AsyncClient, seed_farm_id: str):
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        sectors = resp.json()["sectors_summary"]
        for s in sectors:
            assert "sector_id" in s
            assert "sector_name" in s
            assert "crop_type" in s
            assert "active_alerts" in s
            assert "probe_health" in s

    @pytest.mark.asyncio
    async def test_dashboard_farm_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/farms/00000000-0000-0000-0000-000000000000/dashboard")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_alert_counts_structure(self, client: AsyncClient, seed_farm_id: str):
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        counts = resp.json()["active_alerts_count"]
        assert "critical" in counts
        assert "warning" in counts
        assert "info" in counts
        assert counts["critical"] >= 0

    @pytest.mark.asyncio
    async def test_weather_today_structure(self, client: AsyncClient, seed_farm_id: str):
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        w = resp.json()["weather_today"]
        assert "forecast_rain_next_48h_mm" in w
        assert w["forecast_rain_next_48h_mm"] >= 0


class TestDashboardWithRecommendations:
    @pytest.mark.asyncio
    async def test_generate_then_dashboard_shows_actions(self, client: AsyncClient, seed_farm_id: str):
        """Generate recommendations then check dashboard shows actions."""
        gen_resp = await client.post(f"/api/v1/farms/{seed_farm_id}/recommendations/generate")
        assert gen_resp.status_code == 201
        recs = gen_resp.json()
        assert len(recs) >= 4

        dash_resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        sectors = dash_resp.json()["sectors_summary"]

        sectors_with_action = [s for s in sectors if s["action"] is not None]
        assert len(sectors_with_action) >= 4

    @pytest.mark.asyncio
    async def test_sector_summaries_have_confidence_after_generation(
        self, client: AsyncClient, seed_farm_id: str
    ):
        await client.post(f"/api/v1/farms/{seed_farm_id}/recommendations/generate")
        resp = await client.get(f"/api/v1/farms/{seed_farm_id}/dashboard")
        sectors = resp.json()["sectors_summary"]
        for s in sectors:
            if s["action"] is not None:
                assert s["confidence_score"] is not None
                assert s["confidence_level"] in ("high", "medium", "low")
