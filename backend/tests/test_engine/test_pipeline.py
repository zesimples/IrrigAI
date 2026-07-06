"""Integration tests for the recommendation pipeline.

Requires the Docker database to be running with seed data loaded.
Tests verify:
- All 4 seed sectors produce valid recommendations
- Setor 4 (no phenological stage) uses Kc fallback and penalises confidence
- Sector without irrigation system gets runtime_min = None
- Minimal-config sector gets low confidence
"""

import pytest
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.pipeline import RecommendationPipeline, build_sector_context
from app.engine.types import EngineRecommendation
from app.models import (
    Farm,
    IrrigationSystem,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Sector,
    SectorCropProfile,
    User,
)


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


# ---------------------------------------------------------------------------
# Dose-do-dia — every recommendation carries a dose band + source
# ---------------------------------------------------------------------------
# These build self-contained Farm→Plot→Sector→SectorCropProfile(→Probe) trees
# (same pattern as test_probe_calibration_db.py's _make_pinned_sector) instead
# of relying on seed data, so the water-balance state (reserve vs. depleted) is
# deterministic and doesn't depend on what `make seed` happens to load.

_pipeline = RecommendationPipeline()


async def _make_bare_sector(db: AsyncSession, *, name: str, min_irrigation_mm: float | None = 5.0) -> Sector:
    """Farm→Plot→Sector→SectorCropProfile→IrrigationSystem, no probe (probe-less,
    flowmeter-less → falls back to the static 70%-of-TAW seed in build_water_balance,
    i.e. depletion_mm = 30% of TAW > 0 but usually below RAW → 'reserve' day)."""
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"dose-{name}-{stamp}@t.dev", name="Dose", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name=f"Dose Farm {name}", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", soil_texture="sandy_loam",
                field_capacity=0.30, wilting_point=0.10)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name=name, crop_type="olive")
    db.add(sector)
    await db.flush()
    db.add(SectorCropProfile(
        sector_id=sector.id, crop_type="olive", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3, stages=[],
    ))
    db.add(IrrigationSystem(
        sector_id=sector.id, system_type="drip",
        application_rate_mm_h=2.0, efficiency=0.90, distribution_uniformity=0.90,
        min_irrigation_mm=min_irrigation_mm,
    ))
    await db.flush()
    return sector


async def _make_depleted_sector(db: AsyncSession, *, name: str) -> Sector:
    """Same as _make_bare_sector but with a probe pinned near wilting point,
    forcing depletion_mm well above RAW → engine says 'irrigate', band 'reforcada'."""
    sector = await _make_bare_sector(db, name=name)
    probe = Probe(sector_id=sector.id, external_id=f"{name}-probe")
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    # Plot FC=0.30 / PWP=0.10 → pin VWC near PWP so depletion ≈ TAW (fully depleted).
    base = datetime.now(UTC) - timedelta(hours=2)
    for i in range(3):
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=0.11, calibrated_value=0.11,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.flush()
    return sector


@pytest.fixture
async def seeded_sector_with_reserve(db: AsyncSession) -> Sector:
    return await _make_bare_sector(db, name="Reserve")


@pytest.fixture
async def seeded_sector_depleted(db: AsyncSession) -> Sector:
    return await _make_depleted_sector(db, name="Depleted")


@pytest.mark.asyncio
async def test_skip_recommendation_still_carries_dose(seeded_sector_with_reserve: Sector, db: AsyncSession):
    """Dose-do-dia: reserve days get a reduced dose, not a bare skip."""
    rec = await _pipeline.run(seeded_sector_with_reserve.id, date.today(), db)
    assert rec.action in ("skip", "defer")
    assert rec.irrigation_depth_mm is not None          # dose always computed
    assert rec.dose_band in ("normal", "curta", "pode_saltar")
    assert rec.dose_source in ("configured", "probe_learned", "mm_only")
    await db.rollback()


@pytest.mark.asyncio
async def test_irrigate_recommendation_band_reforcada(seeded_sector_depleted: Sector, db: AsyncSession):
    rec = await _pipeline.run(seeded_sector_depleted.id, date.today(), db)
    assert rec.action == "irrigate"
    assert rec.dose_band == "reforcada"
    await db.rollback()


@pytest.mark.asyncio
async def test_inputs_snapshot_carries_dose_fields(seeded_sector_depleted: Sector, db: AsyncSession):
    from app.services.recommendation_service import generate_recommendation

    rec, eng = await generate_recommendation(str(seeded_sector_depleted.id), db)
    assert rec.inputs_snapshot["dose_band"] == eng.dose_band
    assert rec.inputs_snapshot["dose_source"] == eng.dose_source
    assert "dose_presentation" in rec.inputs_snapshot
    await db.rollback()
