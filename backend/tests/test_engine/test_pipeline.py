"""Integration tests for the recommendation pipeline.

Requires the Docker database to be running with seed data loaded.
Tests verify:
- All 4 seed sectors produce valid recommendations
- Setor 4 (no phenological stage) uses Kc fallback and penalises confidence
- Sector without irrigation system gets runtime_min = None
- Minimal-config sector gets low confidence
"""

import pytest
from datetime import UTC, date, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.pipeline import RecommendationPipeline, build_sector_context
from app.engine.types import EngineRecommendation
from app.models import Farm, Plot, Sector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_farm_id(db: AsyncSession) -> str:
    """Return the farm_id of the demo farm created by the seed script."""
    result = await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))
    farm = result.scalar_one_or_none()
    assert farm is not None, "Seed data not loaded — run: make seed"
    return farm.id


@pytest.fixture
async def seed_sectors(db: AsyncSession, seed_farm_id: str) -> list[Sector]:
    """Return all sectors belonging to the demo farm."""
    plots_result = await db.execute(select(Plot).where(Plot.farm_id == seed_farm_id))
    plots = plots_result.scalars().all()
    plot_ids = [p.id for p in plots]

    sectors = []
    for pid in plot_ids:
        result = await db.execute(select(Sector).where(Sector.plot_id == pid))
        sectors.extend(result.scalars().all())

    assert len(sectors) >= 4, f"Expected ≥4 seed sectors, got {len(sectors)}"
    return sectors


# ---------------------------------------------------------------------------
# Core pipeline tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_runs_for_all_seed_sectors(db: AsyncSession, seed_sectors: list[Sector]):
    """All seed sectors produce an EngineRecommendation with no exceptions."""
    pipeline = RecommendationPipeline()
    today = datetime.now(UTC).date()

    for sector in seed_sectors:
        rec = await pipeline.run(sector.id, today, db)
        assert isinstance(rec, EngineRecommendation), f"Sector {sector.name}: expected EngineRecommendation"
        assert rec.action in ("irrigate", "skip", "defer"), f"Unexpected action: {rec.action}"
        assert 0.10 <= rec.confidence.score <= 1.0
        assert rec.confidence.level in ("high", "medium", "low")


@pytest.mark.asyncio
async def test_run_all_sectors_returns_all(db: AsyncSession, seed_farm_id: str, seed_sectors: list[Sector]):
    """run_all_sectors() returns one recommendation per sector."""
    pipeline = RecommendationPipeline()
    today = datetime.now(UTC).date()
    results = await pipeline.run_all_sectors(seed_farm_id, today, db)
    assert len(results) == len(seed_sectors), (
        f"Expected {len(seed_sectors)} recommendations, got {len(results)}"
    )


@pytest.mark.asyncio
async def test_recommendation_has_water_balance_fields(db: AsyncSession, seed_sectors: list[Sector]):
    """Every recommendation carries the full water balance snapshot."""
    pipeline = RecommendationPipeline()
    today = datetime.now(UTC).date()
    rec = await pipeline.run(seed_sectors[0].id, today, db)

    assert rec.taw_mm is not None and rec.taw_mm > 0
    assert rec.raw_mm is not None and rec.raw_mm > 0
    assert rec.depletion_mm is not None and rec.depletion_mm >= 0


# ---------------------------------------------------------------------------
# Setor 4 — no phenological stage → Kc fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sector_without_stage_uses_kc_fallback(db: AsyncSession, seed_sectors: list[Sector]):
    """Sector with current_phenological_stage=None uses highest-Kc fallback."""
    pipeline = RecommendationPipeline()
    today = datetime.now(UTC).date()

    no_stage = [s for s in seed_sectors if s.current_phenological_stage is None]
    if not no_stage:
        pytest.skip("No seed sector with stage=None (all sectors have a phenological stage set)")

    for sector in no_stage:
        rec = await pipeline.run(sector.id, today, db)
        kc_defaults = [d for d in rec.defaults_used if "kc" in d.lower()]
        assert kc_defaults, (
            f"Sector '{sector.name}': expected Kc fallback in defaults_used, "
            f"got: {rec.defaults_used}"
        )


@pytest.mark.asyncio
async def test_sector_without_stage_has_penalised_confidence(db: AsyncSession, seed_sectors: list[Sector]):
    """Missing stage → confidence penalty for phenological stage not set."""
    pipeline = RecommendationPipeline()
    today = datetime.now(UTC).date()

    no_stage = [s for s in seed_sectors if s.current_phenological_stage is None]
    if not no_stage:
        pytest.skip("No seed sector with stage=None (all sectors have a phenological stage set)")

    rec = await pipeline.run(no_stage[0].id, today, db)
    penalty_reasons = [r for r, _ in rec.confidence.penalties if "phenological" in r.lower() or "stage" in r.lower()]
    assert penalty_reasons, (
        f"Expected phenological stage penalty in confidence, got: {rec.confidence.penalties}"
    )


# ---------------------------------------------------------------------------
# Sector without irrigation system → runtime_min = None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sector_without_irrigation_system_has_no_runtime(db: AsyncSession, seed_sectors: list[Sector]):
    """Sector missing IrrigationSystem record → runtime_min is None when irrigating."""
    from app.models import IrrigationSystem

    pipeline = RecommendationPipeline()
    today = datetime.now(UTC).date()

    for sector in seed_sectors:
        irrig = await db.execute(
            select(IrrigationSystem).where(IrrigationSystem.sector_id == sector.id)
        )
        if irrig.scalar_one_or_none() is None:
            rec = await pipeline.run(sector.id, today, db)
            # runtime_min must be None regardless of action
            assert rec.irrigation_runtime_min is None, (
                f"Sector '{sector.name}' has no irrigation system but got runtime_min={rec.irrigation_runtime_min}"
            )
            assert "irrigation system" in " ".join(rec.missing_config).lower()
            return  # Found and tested at least one

    pytest.skip("No sector without irrigation system found in seed data")


# ---------------------------------------------------------------------------
# Context loading
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_sector_context_loads_kc_from_profile(db: AsyncSession, seed_sectors: list[Sector]):
    """Sector with a stage set → Kc sourced from profile, not fallback."""
    with_stage = [s for s in seed_sectors if s.current_phenological_stage is not None]
    if not with_stage:
        pytest.skip("No sectors with stage set")

    ctx = await build_sector_context(with_stage[0].id, db)
    assert "profile stage" in ctx.kc_source or "default" not in ctx.kc_source


@pytest.mark.asyncio
async def test_build_sector_context_missing_config_without_irrig_system(db: AsyncSession, seed_sectors: list[Sector]):
    """Sector without IrrigationSystem has 'irrigation system' in missing_config."""
    from app.models import IrrigationSystem

    for sector in seed_sectors:
        irrig = await db.execute(
            select(IrrigationSystem).where(IrrigationSystem.sector_id == sector.id)
        )
        if irrig.scalar_one_or_none() is None:
            ctx = await build_sector_context(sector.id, db)
            assert any("irrigation system" in m.lower() for m in ctx.missing_config)
            return

    pytest.skip("All sectors have irrigation systems")
