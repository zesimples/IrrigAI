"""API tests: PUT /sectors/{id}/crop-profile regenerates the recommendation when
soil bounds (field_capacity/wilting_point/soil_preset_id) change, so the displayed
depletion doesn't stay frozen until the next scheduled/manual generation.

Uses the globally-seeded "Herdade do Esporão" farm/sector (mirrors
test_recommendations.py's seed_farm_id/seed_sector_id fixtures) — reused read-only,
no new farm subtree to clean up.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Farm, Plot, Recommendation, Sector, SectorCropProfile


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_sector_id(db: AsyncSession):
    farm = (await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))).scalar_one()
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm.id))).scalars().first()
    sector = (await db.execute(select(Sector).where(Sector.plot_id == plot.id))).scalars().first()

    # These tests PUT soil/mad edits to this SHARED, globally-seeded sector. Snapshot
    # the crop-profile fields and restore them afterwards so we don't corrupt the
    # seeded data for other suites (e.g. test_context_loading asserts this sector's mad).
    scp = (
        await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector.id)
        )
    ).scalar_one_or_none()
    snap = None
    if scp is not None:
        snap = (
            scp.field_capacity, scp.wilting_point, scp.mad,
            scp.soil_preset_id, scp.is_customized,
        )
    try:
        yield sector.id
    finally:
        if snap is not None:
            fc, wp, mad, preset, cust = snap
            # Core UPDATE (not ORM) to avoid identity-map/lazy-load greenlet issues
            # in async teardown; the client PUTs committed via a different session.
            await db.execute(
                update(SectorCropProfile)
                .where(SectorCropProfile.sector_id == sector.id)
                .values(
                    field_capacity=fc, wilting_point=wp, mad=mad,
                    soil_preset_id=preset, is_customized=cust,
                )
            )
            await db.commit()


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


@pytest.mark.asyncio
async def test_regeneration_failure_still_saves_profile(
    client: AsyncClient, db: AsyncSession, seed_sector_id: str, monkeypatch
):
    """A failing regeneration must NOT lose the soil edit or 500 the request.

    CI uses mock providers that always succeed, so the best-effort try/except
    (and its rollback) is otherwise never exercised — force generation to raise
    and assert the PUT still returns 200 with the updated FC and no extra rec.
    """
    import app.api.v1.crop_profiles as crop_profiles_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated pipeline failure")

    monkeypatch.setattr(crop_profiles_module, "generate_recommendation", _boom)

    before = await _rec_count(db, seed_sector_id)
    resp = await client.get(f"/api/v1/sectors/{seed_sector_id}/crop-profile")
    current_fc = resp.json()["field_capacity"] or 0.20
    new_fc = round(current_fc + 0.017, 3)

    put_resp = await client.put(
        f"/api/v1/sectors/{seed_sector_id}/crop-profile",
        json={"field_capacity": new_fc},
    )
    # Edit is preserved and returned; no 500 from a PendingRollbackError at teardown.
    assert put_resp.status_code == 200
    assert put_resp.json()["field_capacity"] == pytest.approx(new_fc)
    # Regeneration failed → no new recommendation persisted.
    assert await _rec_count(db, seed_sector_id) == before
