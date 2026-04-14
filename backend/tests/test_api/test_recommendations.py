"""API tests for the recommendations endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Farm, Plot, Sector


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


@pytest.fixture
async def seed_sector_id(db: AsyncSession) -> str:
    farm = (await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))).scalar_one()
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm.id))).scalars().first()
    sector = (await db.execute(select(Sector).where(Sector.plot_id == plot.id))).scalars().first()
    return sector.id


class TestGenerateRecommendation:
    @pytest.mark.asyncio
    async def test_generate_sector_returns_201(self, client: AsyncClient, seed_sector_id: str):
        resp = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_generate_sector_returns_valid_rec(self, client: AsyncClient, seed_sector_id: str):
        resp = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        data = resp.json()
        assert data["action"] in ("irrigate", "skip", "defer")
        assert 0.0 <= data["confidence_score"] <= 1.0
        assert data["confidence_level"] in ("high", "medium", "low")
        assert data["sector_id"] == seed_sector_id

    @pytest.mark.asyncio
    async def test_generate_farm_returns_all_sectors(self, client: AsyncClient, seed_farm_id: str):
        resp = await client.post(f"/api/v1/farms/{seed_farm_id}/recommendations/generate")
        assert resp.status_code == 201
        recs = resp.json()
        assert len(recs) >= 4

    @pytest.mark.asyncio
    async def test_generate_farm_not_found(self, client: AsyncClient):
        resp = await client.post("/api/v1/farms/00000000-0000-0000-0000-000000000000/recommendations/generate")
        assert resp.status_code == 404


class TestGetRecommendation:
    @pytest.mark.asyncio
    async def test_get_detail_has_reasons(self, client: AsyncClient, seed_sector_id: str):
        gen = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        rec_id = gen.json()["id"]

        resp = await client.get(f"/api/v1/recommendations/{rec_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "reasons" in data
        assert len(data["reasons"]) >= 1

    @pytest.mark.asyncio
    async def test_get_detail_has_computation_log(self, client: AsyncClient, seed_sector_id: str):
        gen = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        rec_id = gen.json()["id"]

        resp = await client.get(f"/api/v1/recommendations/{rec_id}")
        data = resp.json()
        assert "computation_log" in data
        assert "log" in data["computation_log"]

    @pytest.mark.asyncio
    async def test_get_detail_has_inputs_snapshot(self, client: AsyncClient, seed_sector_id: str):
        gen = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        rec_id = gen.json()["id"]

        resp = await client.get(f"/api/v1/recommendations/{rec_id}")
        data = resp.json()
        snap = data["inputs_snapshot"]
        assert "et0_mm" in snap
        assert "depletion_mm" in snap

    @pytest.mark.asyncio
    async def test_get_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/recommendations/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_sector_recommendations(self, client: AsyncClient, seed_sector_id: str):
        await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        resp = await client.get(f"/api/v1/sectors/{seed_sector_id}/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1


class TestAcceptRejectOverride:
    @pytest.mark.asyncio
    async def test_accept_recommendation(self, client: AsyncClient, seed_sector_id: str):
        gen = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        rec_id = gen.json()["id"]

        resp = await client.post(f"/api/v1/recommendations/{rec_id}/accept", json={"notes": "Looks good"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_accepted"] is True
        assert data["accepted_at"] is not None

    @pytest.mark.asyncio
    async def test_reject_recommendation(self, client: AsyncClient, seed_sector_id: str):
        gen = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        rec_id = gen.json()["id"]

        resp = await client.post(
            f"/api/v1/recommendations/{rec_id}/reject",
            json={"notes": "Will irrigate manually"},
        )
        assert resp.status_code == 200
        assert resp.json()["is_accepted"] is False

    @pytest.mark.asyncio
    async def test_override_recommendation(self, client: AsyncClient, seed_sector_id: str):
        gen = await client.post(f"/api/v1/sectors/{seed_sector_id}/recommendations/generate")
        rec_id = gen.json()["id"]

        resp = await client.post(
            f"/api/v1/recommendations/{rec_id}/override",
            json={"irrigation_depth_mm": 8.0, "notes": "Agronomist override"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["irrigation_depth_mm"] == 8.0
        assert data["is_accepted"] is True
