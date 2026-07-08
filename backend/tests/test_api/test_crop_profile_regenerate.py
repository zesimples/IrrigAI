"""API tests: PUT /sectors/{id}/crop-profile regenerates the recommendation when
soil bounds (field_capacity/wilting_point/soil_preset_id) change, so the displayed
depletion doesn't stay frozen until the next scheduled/manual generation.

Uses the globally-seeded "Herdade do Esporão" farm/sector (mirrors
test_recommendations.py's seed_farm_id/seed_sector_id fixtures) — reused read-only,
no new farm subtree to clean up.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Farm, Plot, Recommendation, Sector


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


async def _rec_count(db: AsyncSession, sector_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Recommendation).where(
                Recommendation.sector_id == sector_id
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_soil_edit_regenerates_recommendation(
    client: AsyncClient, db: AsyncSession, seed_sector_id: str
):
    before = await _rec_count(db, seed_sector_id)

    resp = await client.get(f"/api/v1/sectors/{seed_sector_id}/crop-profile")
    assert resp.status_code == 200
    current_fc = resp.json()["field_capacity"] or 0.20
    new_fc = round(current_fc + 0.03, 3)

    put_resp = await client.put(
        f"/api/v1/sectors/{seed_sector_id}/crop-profile",
        json={"field_capacity": new_fc},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["field_capacity"] == pytest.approx(new_fc)

    after = await _rec_count(db, seed_sector_id)
    # Exactly one new recommendation was generated (best-effort regenerate, not more).
    assert after == before + 1


@pytest.mark.asyncio
async def test_non_soil_edit_does_not_regenerate(
    client: AsyncClient, db: AsyncSession, seed_sector_id: str
):
    before = await _rec_count(db, seed_sector_id)

    # `mad` (management allowed depletion) is accepted by SectorCropProfileUpdate
    # but is not one of the soil-bounds fields that trigger regeneration.
    resp = await client.get(f"/api/v1/sectors/{seed_sector_id}/crop-profile")
    assert resp.status_code == 200
    current_mad = resp.json()["mad"]
    new_mad = round(min(max(current_mad + 0.05, 0.1), 0.9), 3)

    put_resp = await client.put(
        f"/api/v1/sectors/{seed_sector_id}/crop-profile",
        json={"mad": new_mad},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["mad"] == pytest.approx(new_mad)

    after = await _rec_count(db, seed_sector_id)
    assert after == before
