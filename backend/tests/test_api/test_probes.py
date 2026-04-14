"""API tests for the probes endpoint including readings filtering."""

import pytest
from datetime import UTC, datetime, timedelta
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Farm, Plot, Probe, Sector


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_sector_id(db: AsyncSession) -> str:
    farm = (await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))).scalar_one()
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm.id))).scalars().first()
    sector = (await db.execute(select(Sector).where(Sector.plot_id == plot.id))).scalars().first()
    return sector.id


@pytest.fixture
async def seed_probe_id(db: AsyncSession, seed_sector_id: str) -> str:
    probe = (
        await db.execute(select(Probe).where(Probe.sector_id == seed_sector_id))
    ).scalars().first()
    assert probe is not None, "No probe found in seed data"
    return probe.id


class TestProbeList:
    @pytest.mark.asyncio
    async def test_list_probes_returns_200(self, client: AsyncClient, seed_sector_id: str):
        resp = await client.get(f"/api/v1/sectors/{seed_sector_id}/probes")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_probes_has_items(self, client: AsyncClient, seed_sector_id: str):
        resp = await client.get(f"/api/v1/sectors/{seed_sector_id}/probes")
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_list_probes_sector_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/sectors/00000000-0000-0000-0000-000000000000/probes")
        assert resp.status_code == 404


class TestProbeDetail:
    @pytest.mark.asyncio
    async def test_get_probe_returns_200(self, client: AsyncClient, seed_probe_id: str):
        resp = await client.get(f"/api/v1/probes/{seed_probe_id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_probe_detail_has_depths(self, client: AsyncClient, seed_probe_id: str):
        resp = await client.get(f"/api/v1/probes/{seed_probe_id}")
        data = resp.json()
        assert "depths" in data
        assert len(data["depths"]) >= 1

    @pytest.mark.asyncio
    async def test_probe_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/probes/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestProbeReadings:
    @pytest.mark.asyncio
    async def test_readings_grouped_by_depth(self, client: AsyncClient, seed_probe_id: str):
        resp = await client.get(f"/api/v1/probes/{seed_probe_id}/readings")
        assert resp.status_code == 200
        data = resp.json()
        assert "depths" in data
        assert "reference_lines" in data
        assert len(data["depths"]) >= 1

    @pytest.mark.asyncio
    async def test_readings_depth_filter(self, client: AsyncClient, seed_probe_id: str):
        resp = await client.get(
            f"/api/v1/probes/{seed_probe_id}/readings",
            params={"depth_cm": "10,30"},
        )
        assert resp.status_code == 200
        data = resp.json()
        returned_depths = {d["depth_cm"] for d in data["depths"]}
        # Should only return depths 10 and/or 30
        assert returned_depths.issubset({10, 30})

    @pytest.mark.asyncio
    async def test_readings_time_range_filter(self, client: AsyncClient, seed_probe_id: str):
        now = datetime.now(UTC)
        since = (now - timedelta(hours=24)).isoformat()
        until = now.isoformat()
        resp = await client.get(
            f"/api/v1/probes/{seed_probe_id}/readings",
            params={"since": since, "until": until},
        )
        assert resp.status_code == 200
        data = resp.json()
        for depth in data["depths"]:
            for pt in depth["readings"]:
                ts = datetime.fromisoformat(pt["timestamp"])
                if ts.tzinfo is None:
                    from datetime import timezone
                    ts = ts.replace(tzinfo=timezone.utc)
                # Allow slight tolerance on boundaries
                assert ts >= (now - timedelta(hours=25))

    @pytest.mark.asyncio
    async def test_readings_downsampling_reduces_points(self, client: AsyncClient, seed_probe_id: str):
        now = datetime.now(UTC)
        since = (now - timedelta(days=7)).isoformat()

        resp_full = await client.get(
            f"/api/v1/probes/{seed_probe_id}/readings",
            params={"since": since},
        )
        resp_sampled = await client.get(
            f"/api/v1/probes/{seed_probe_id}/readings",
            params={"since": since, "interval": "6h"},
        )

        assert resp_full.status_code == 200
        assert resp_sampled.status_code == 200

        full_depths = resp_full.json()["depths"]
        sampled_depths = resp_sampled.json()["depths"]

        if full_depths and sampled_depths:
            full_count = sum(len(d["readings"]) for d in full_depths)
            sampled_count = sum(len(d["readings"]) for d in sampled_depths)
            assert sampled_count <= full_count

    @pytest.mark.asyncio
    async def test_readings_reference_lines(self, client: AsyncClient, seed_probe_id: str):
        resp = await client.get(f"/api/v1/probes/{seed_probe_id}/readings")
        ref = resp.json()["reference_lines"]
        # Seed has soil configured — should have FC and PWP
        if ref["field_capacity"] is not None:
            assert 0.10 <= ref["field_capacity"] <= 0.60
        if ref["wilting_point"] is not None:
            assert 0.05 <= ref["wilting_point"] <= 0.40

    @pytest.mark.asyncio
    async def test_invalid_interval_returns_400(self, client: AsyncClient, seed_probe_id: str):
        resp = await client.get(
            f"/api/v1/probes/{seed_probe_id}/readings",
            params={"interval": "bogus"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_readings_points_have_quality_flag(self, client: AsyncClient, seed_probe_id: str):
        resp = await client.get(f"/api/v1/probes/{seed_probe_id}/readings")
        for depth in resp.json()["depths"]:
            for pt in depth["readings"][:3]:
                assert "quality" in pt
                assert pt["quality"] in ("ok", "suspect", "invalid")
