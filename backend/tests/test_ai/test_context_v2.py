"""Contract tests for the canonical sector AI context."""

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.context_builder import build_sector_ai_context_v2
from app.ai.context_v2 import SECTOR_AI_CONTEXT_BLOCKS, SectorAIContextV2
from app.config import get_settings
from app.core.enums import ConfidenceLevel, RecommendationAction
from app.models import (
    Farm,
    IrrigationFingerprint,
    Plot,
    ProbeCalibrationRun,
    Recommendation,
    RecommendationOutcome,
    Sector,
)


@pytest.fixture
async def async_db_session():
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_sector_id(async_db_session: AsyncSession) -> str:
    farm = (
        await async_db_session.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))
    ).scalar_one()
    plot = (
        await async_db_session.execute(select(Plot).where(Plot.farm_id == farm.id))
    ).scalars().first()
    sector = (
        await async_db_session.execute(select(Sector).where(Sector.plot_id == plot.id))
    ).scalars().first()
    return sector.id


def _block(source: str = "test") -> dict:
    return {
        "observed_at": "2026-07-20T10:00:00+00:00",
        "source": source,
        "units": {},
    }


def test_sector_ai_context_v2_has_exact_canonical_blocks():
    context = SectorAIContextV2(**{name: _block() for name in SECTOR_AI_CONTEXT_BLOCKS})

    payload = context.to_dict()

    assert payload["schema_version"] == "2.0"
    assert tuple(key for key in payload if key != "schema_version") == SECTOR_AI_CONTEXT_BLOCKS
    assert json.loads(context.to_json()) == payload


def test_sector_ai_context_v2_rejects_block_without_provenance():
    blocks = {name: _block() for name in SECTOR_AI_CONTEXT_BLOCKS}
    blocks["weather"] = {"forecast": []}

    with pytest.raises(ValueError, match="weather.*observed_at.*source.*units"):
        SectorAIContextV2(**blocks)


@pytest.mark.asyncio
async def test_sector_ai_context_v2_uses_snapshot_and_shared_resolvers(
    async_db_session,
    seed_sector_id,
):
    context = await build_sector_ai_context_v2(
        seed_sector_id,
        async_db_session,
        compact=False,
    )
    payload = context.to_dict()

    assert tuple(key for key in payload if key != "schema_version") == SECTOR_AI_CONTEXT_BLOCKS
    assert payload["scope"]["sector"]["id"] == seed_sector_id
    assert payload["engine_decision"]["source"] == "recommendation.inputs_snapshot"
    assert payload["water_balance"]["source"] == "recommendation.inputs_snapshot"
    assert payload["weather"]["source"] == "engine.weather_scope_resolver"
    assert payload["calibration"]["source"] == "engine.resolve_sector_soil_bounds"
    assert isinstance(payload["outcomes"]["recent"], list)
    assert "gdd" in payload["crop_state"]
    assert "habitual_dose" in payload["irrigation_execution"]


@pytest.mark.asyncio
async def test_sector_ai_context_v2_compact_digest_keeps_decision_authority(
    async_db_session,
    seed_sector_id,
):
    context = await build_sector_ai_context_v2(
        seed_sector_id,
        async_db_session,
        compact=True,
    )
    payload = context.to_dict()

    assert payload["scope"]["detail_level"] == "compact"
    assert "history" not in payload["engine_decision"]
    assert "recent" not in payload["outcomes"]
    assert "diagnostics" not in payload["probe_state"]
    assert "action" in payload["engine_decision"]
    assert "depletion_mm" in payload["water_balance"]


@pytest.mark.asyncio
async def test_sector_ai_context_v2_surfaces_snapshot_outcome_fingerprint_and_candidate(
    async_db_session,
    seed_sector_id,
):
    now = datetime.now(UTC)
    recommendation = Recommendation(
        sector_id=seed_sector_id,
        generated_at=now,
        target_date=date.today(),
        action=RecommendationAction.IRRIGATE,
        irrigation_depth_mm=18.0,
        irrigation_runtime_min=90.0,
        confidence_score=0.82,
        confidence_level=ConfidenceLevel.HIGH,
        engine_version="test",
        inputs_snapshot={
            "depletion_mm": 14.0,
            "taw_mm": 30.0,
            "raw_mm": 15.0,
            "etc_mm": 4.2,
            "swc_source": "probe_weighted",
            "dose_band": "normal",
            "stress_projection": {"urgency": "low"},
        },
        computation_log={"confidence_penalties": ["weather_stale"]},
    )
    async_db_session.add(recommendation)
    await async_db_session.flush()
    async_db_session.add(
        RecommendationOutcome(
            recommendation_id=recommendation.id,
            sector_id=seed_sector_id,
            evaluated_at=now,
            status="matched",
            recommended_depth_mm=18.0,
            actual_applied_mm=17.0,
            dose_error_mm=-1.0,
            dose_error_pct=-5.6,
            details={},
        )
    )
    fingerprint = (
        await async_db_session.execute(
            select(IrrigationFingerprint).where(
                IrrigationFingerprint.sector_id == seed_sector_id
            )
        )
    ).scalar_one_or_none()
    if fingerprint is None:
        async_db_session.add(
            IrrigationFingerprint(
                sector_id=seed_sector_id,
                typical_event_net_mm=16.0,
                typical_event_duration_min=80.0,
                n_events=5,
                consistency=0.9,
                confidence="high",
                window_days=25,
                computed_at=now,
            )
        )
    else:
        fingerprint.typical_event_net_mm = 16.0
    async_db_session.add(
        ProbeCalibrationRun(
            sector_id=seed_sector_id,
            observed_fc=0.31,
            observed_refill=0.18,
            method="envelope",
            num_cycles=0,
            consistency=0.7,
            window_days=60,
            computed_at=now,
            source="scheduled",
            status="candidate",
        )
    )
    await async_db_session.flush()

    payload = (
        await build_sector_ai_context_v2(seed_sector_id, async_db_session, compact=False)
    ).to_dict()

    assert payload["engine_decision"]["action"] == "irrigate"
    assert payload["water_balance"]["depletion_mm"] == 14.0
    assert payload["water_balance"]["etc_mm"] == 4.2
    assert payload["crop_state"]["stress_projection"] == {"urgency": "low"}
    assert payload["outcomes"]["recent"][0]["status"] == "matched"
    assert payload["irrigation_execution"]["habitual_dose"][
        "typical_event_net_mm"
    ] == 16.0
    assert payload["calibration"]["pending_candidate_count"] >= 1
    assert payload["calibration"]["runs"][0]["status"] == "candidate"

    await async_db_session.rollback()
