"""Integration tests for pipeline context loading from DB.

Verifies that build_sector_context() correctly reads user-configured records
and falls back gracefully when config is missing.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.pipeline import build_sector_context
from app.models import Farm, IrrigationSystem, Plot, Sector, SectorCropProfile


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_sectors(db: AsyncSession) -> list[Sector]:
    result = await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))
    farm = result.scalar_one_or_none()
    assert farm is not None, "Seed data not loaded"

    plots = (await db.execute(select(Plot).where(Plot.farm_id == farm.id))).scalars().all()
    sectors = []
    for p in plots:
        s = (await db.execute(select(Sector).where(Sector.plot_id == p.id))).scalars().all()
        sectors.extend(s)
    return sectors


class TestFullyConfiguredSector:
    """A sector with all fields set returns sane context."""

    @pytest.mark.asyncio
    async def test_ctx_has_positive_kc(self, db: AsyncSession, seed_sectors: list[Sector]):
        sector = seed_sectors[0]
        ctx = await build_sector_context(sector.id, db)
        assert ctx.kc > 0

    @pytest.mark.asyncio
    async def test_ctx_crop_type_matches_sector(self, db: AsyncSession, seed_sectors: list[Sector]):
        sector = seed_sectors[0]
        ctx = await build_sector_context(sector.id, db)
        assert ctx.crop_type == sector.crop_type

    @pytest.mark.asyncio
    async def test_ctx_mad_in_range(self, db: AsyncSession, seed_sectors: list[Sector]):
        sector = seed_sectors[0]
        ctx = await build_sector_context(sector.id, db)
        assert 0.3 <= ctx.mad <= 0.8, f"MAD out of plausible range: {ctx.mad}"

    @pytest.mark.asyncio
    async def test_ctx_root_depth_positive(self, db: AsyncSession, seed_sectors: list[Sector]):
        sector = seed_sectors[0]
        ctx = await build_sector_context(sector.id, db)
        assert ctx.root_depth_m > 0

    @pytest.mark.asyncio
    async def test_ctx_field_capacity_reasonable(self, db: AsyncSession, seed_sectors: list[Sector]):
        sector = seed_sectors[0]
        ctx = await build_sector_context(sector.id, db)
        assert 0.10 <= ctx.field_capacity <= 0.60


class TestMissingStageSector:
    """Sector with phenological_stage=None falls back to highest Kc."""

    @pytest.mark.asyncio
    async def test_kc_source_indicates_fallback(self, db: AsyncSession, seed_sectors: list[Sector]):
        no_stage = [s for s in seed_sectors if s.current_phenological_stage is None]
        if not no_stage:
            pytest.skip("All sectors have stage set")
        ctx = await build_sector_context(no_stage[0].id, db)
        assert "default" in ctx.kc_source or "highest" in ctx.kc_source

    @pytest.mark.asyncio
    async def test_kc_default_in_defaults_used(self, db: AsyncSession, seed_sectors: list[Sector]):
        no_stage = [s for s in seed_sectors if s.current_phenological_stage is None]
        if not no_stage:
            pytest.skip("All sectors have stage set")
        ctx = await build_sector_context(no_stage[0].id, db)
        assert any("kc" in d.lower() for d in ctx.defaults_used)


class TestNoIrrigationSystemSector:
    """Sector without IrrigationSystem has missing_config populated."""

    @pytest.mark.asyncio
    async def test_missing_config_contains_irrigation_system(self, db: AsyncSession, seed_sectors: list[Sector]):
        for sector in seed_sectors:
            irrig = (await db.execute(
                select(IrrigationSystem).where(IrrigationSystem.sector_id == sector.id)
            )).scalar_one_or_none()
            if irrig is None:
                ctx = await build_sector_context(sector.id, db)
                assert any("irrigation system" in m.lower() for m in ctx.missing_config)
                assert ctx.application_rate_mm_h is None
                return
        pytest.skip("All sectors have irrigation systems in seed data")

    @pytest.mark.asyncio
    async def test_efficiency_falls_back_to_default(self, db: AsyncSession, seed_sectors: list[Sector]):
        for sector in seed_sectors:
            irrig = (await db.execute(
                select(IrrigationSystem).where(IrrigationSystem.sector_id == sector.id)
            )).scalar_one_or_none()
            if irrig is None:
                ctx = await build_sector_context(sector.id, db)
                assert ctx.irrigation_efficiency == 0.90  # _FALLBACK_EFFICIENCY
                return
        pytest.skip("All sectors have irrigation systems")


class TestKcLookup:
    """Kc lookup directly from SectorCropProfile stages JSONB."""

    @pytest.mark.asyncio
    async def test_kc_from_stage_matches_profile(self, db: AsyncSession, seed_sectors: list[Sector]):
        """Sector with a stage set → Kc matches corresponding profile stage entry."""
        from app.engine.crop_demand import get_kc_from_profile

        with_stage = [s for s in seed_sectors if s.current_phenological_stage is not None]
        if not with_stage:
            pytest.skip("No sectors with stage set")

        sector = with_stage[0]
        scp = (await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector.id)
        )).scalar_one_or_none()

        if scp is None or not scp.stages:
            pytest.skip("Sector has no crop profile stages")

        kc, source = get_kc_from_profile(scp.stages, sector.current_phenological_stage)
        ctx = await build_sector_context(sector.id, db)
        assert ctx.kc == kc
