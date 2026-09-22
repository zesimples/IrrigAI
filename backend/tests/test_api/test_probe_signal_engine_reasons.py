"""The probe-signal stats must carry the engine's own reason and freshness.

The A1 guard quotes ``latest_recommendation.reasons`` instead of inventing a
justification, and grades risk from ``probe_state``. Both are produced by a real
query against the probe's sector, so this exercises it against Postgres rather
than a mocked stats dict.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.probe_signal import compute_probe_signal_stats
from app.core.enums import ConfidenceLevel, RecommendationAction
from app.models import (
    Farm,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Recommendation,
    RecommendationReason,
    Sector,
    User,
)
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"


@pytest.fixture
async def probe_sector(db: AsyncSession):
    owner = (await db.execute(select(User).where(User.email == _OWNER_EMAIL))).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    farm = Farm(name="Probe Signal Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.30, wilting_point=0.14)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Probe Signal Sector", crop_type="olive")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id="1597/probe-signal-test")
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=30, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()

    now = datetime.now(UTC)
    for index in range(12):
        db.add(
            ProbeReading(
                probe_depth_id=depth.id,
                timestamp=now - timedelta(hours=index * 2),
                raw_value=0.28 - index * 0.001,
                calibrated_value=0.28 - index * 0.001,
                unit="vwc_m3m3",
                quality_flag="ok",
            )
        )
    recommendation = Recommendation(
        sector_id=sector.id,
        generated_at=now,
        target_date=now.date(),
        action=RecommendationAction.DEFER,
        confidence_score=0.72,
        confidence_level=ConfidenceLevel.MEDIUM,
        inputs_snapshot={"depletion_mm": 12.0, "taw_mm": 90.0},
    )
    db.add(recommendation)
    await db.flush()
    db.add(
        RecommendationReason(
            recommendation_id=recommendation.id,
            order=1,
            category="weather",
            message_pt="Chuva prevista nas próximas 48 horas.",
            message_en="Rain forecast in the next 48 hours.",
        )
    )
    await db.commit()
    ids = {"probe_id": probe.id, "farm_id": farm.id}
    yield ids
    await delete_farm_subtree(db, ids["farm_id"])


@pytest.mark.asyncio
async def test_stats_carry_the_engine_reason_and_confidence(db, probe_sector):
    stats = await compute_probe_signal_stats(probe_sector["probe_id"], db)

    latest = stats["latest_recommendation"]
    assert latest["action"] == "defer"
    assert latest["confidence_level"] == "medium"
    assert [reason["message"] for reason in latest["reasons"]] == [
        "Chuva prevista nas próximas 48 horas."
    ]


@pytest.mark.asyncio
async def test_stats_expose_the_canonical_probe_state_block(db, probe_sector):
    stats = await compute_probe_signal_stats(probe_sector["probe_id"], db)

    quality = stats["probe_state"]["data_quality"]
    assert quality["total_depths"] == 1
    assert quality["fresh_depths"] == 1
    assert quality["stale_depths"] == 0
    assert stats["probe_state"]["live"] is not None


@pytest.mark.asyncio
async def test_the_guard_quotes_that_reason_end_to_end(db, probe_sector):
    from app.ai.assistant import IrrigationAssistant
    from app.ai.context_builder import AssistantContextBuilder
    from app.ai.openai_client import MockChatClient
    from app.schemas.ai import AgronomicInterpretation

    stats = await compute_probe_signal_stats(probe_sector["probe_id"], db)
    assistant = IrrigationAssistant(AssistantContextBuilder(), MockChatClient(), "pt")

    guarded = assistant._apply_probe_recommendation_guard(
        stats,
        AgronomicInterpretation(
            summary="Humidade baixa em profundidade.",
            risk_level="high",
            irrigation_advice="Rega urgente.",
            evidence=[],
            missing_data=[],
            confidence_score=0.4,
            confidence_explanation="modelo",
            recommended_actions=["Aplicar rega imediatamente."],
        ),
    )

    assert "Chuva prevista nas próximas 48 horas." in guarded.irrigation_advice
    assert guarded.confidence.engine_confidence == "medium"
    assert guarded.confidence.data_quality == "fresh"
    assert guarded.risk_level == "low"
