"""Shared fixtures for E2E tests.

All E2E tests require a running PostgreSQL with the seed data applied.
The `client` fixture overrides the DB dependency to use NullPool (one conn per
request), avoiding event-loop conflicts under pytest-asyncio.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import CropProfileTemplate, Farm, Plot, Sector, SectorCropProfile, SoilPreset


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture
async def db(settings):
    """Direct async DB session (NullPool) for fixtures and assertions."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(settings):
    """HTTP client with DB overridden to NullPool per request."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Seeded data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def seed_farm_id(db: AsyncSession) -> str:
    farm = (
        await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))
    ).scalar_one()
    return farm.id


@pytest.fixture
async def seed_sector_ids(db: AsyncSession, seed_farm_id: str) -> list[str]:
    """Return all sector IDs for the seeded demo farm, ordered by name."""
    plots = (
        await db.execute(select(Plot).where(Plot.farm_id == seed_farm_id))
    ).scalars().all()
    plot_ids = [p.id for p in plots]

    sectors = []
    for plot_id in plot_ids:
        result = await db.execute(select(Sector).where(Sector.plot_id == plot_id))
        sectors.extend(result.scalars().all())

    sectors.sort(key=lambda s: s.name)
    return [s.id for s in sectors]


@pytest.fixture
async def olive_template(db: AsyncSession) -> CropProfileTemplate:
    tmpl = (
        await db.execute(
            select(CropProfileTemplate).where(
                CropProfileTemplate.crop_type == "olive",
                CropProfileTemplate.is_system_default.is_(True),
            )
        )
    ).scalar_one()
    return tmpl


@pytest.fixture
async def sandy_loam_preset(db: AsyncSession) -> SoilPreset:
    preset = (
        await db.execute(
            select(SoilPreset).where(SoilPreset.texture == "sandy_loam")
        )
    ).scalar_one()
    return preset


@pytest.fixture
async def clay_loam_preset(db: AsyncSession) -> SoilPreset:
    preset = (
        await db.execute(
            select(SoilPreset).where(SoilPreset.texture == "clay_loam")
        )
    ).scalar_one()
    return preset


# ---------------------------------------------------------------------------
# Helper: create a minimal test farm via API and return its ID
# ---------------------------------------------------------------------------

async def api_create_farm(client: AsyncClient, name: str = "Quinta de Teste") -> str:
    resp = await client.post("/api/v1/farms", json={"name": name, "timezone": "Europe/Lisbon"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def api_create_plot(
    client: AsyncClient,
    farm_id: str,
    name: str = "Bloco A",
    soil_preset_id: str | None = None,
    fc: float | None = None,
    pwp: float | None = None,
) -> str:
    body: dict = {"name": name}
    if soil_preset_id:
        body["soil_preset_id"] = soil_preset_id
    if fc is not None:
        body["field_capacity"] = fc
    if pwp is not None:
        body["wilting_point"] = pwp
    resp = await client.post(f"/api/v1/farms/{farm_id}/plots", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def api_create_sector(
    client: AsyncClient,
    plot_id: str,
    name: str = "Setor Teste",
    crop_type: str = "olive",
    stage: str | None = "olive_oil_accumulation",
) -> str:
    body: dict = {"name": name, "crop_type": crop_type}
    if stage:
        body["current_phenological_stage"] = stage
    resp = await client.post(f"/api/v1/plots/{plot_id}/sectors", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def api_add_irrigation_system(
    client: AsyncClient,
    sector_id: str,
    system_type: str = "drip",
    emitter_flow_lph: float = 2.3,
    emitter_spacing_m: float = 0.75,
) -> None:
    resp = await client.post(
        f"/api/v1/sectors/{sector_id}/irrigation-systems",
        json={
            "system_type": system_type,
            "emitter_flow_lph": emitter_flow_lph,
            "emitter_spacing_m": emitter_spacing_m,
            "efficiency": 0.90,
        },
    )
    assert resp.status_code in (200, 201), resp.text
