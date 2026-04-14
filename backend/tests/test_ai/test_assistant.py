"""Tests for IrrigationAssistant using MockChatClient and mocked context builder."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.assistant import IrrigationAssistant
from app.ai.context_builder import AssistantContextBuilder, FarmAssistantContext, SectorAssistantContext
from app.ai.openai_client import MockChatClient


def _sector_ctx(**overrides) -> SectorAssistantContext:
    defaults = dict(
        sector_id="sec-001",
        sector_name="Norte",
        crop_type="olive",
        variety=None,
        phenological_stage="vegetative_growth",
        area_ha=5.0,
        config_status={"soil": "configured", "irrigation_system": "missing"},
        defaults_used=["Kc=0.65"],
        missing_config=["irrigation system not configured"],
        recommendation_action="irrigate",
        irrigation_depth_mm=18.5,
        runtime_minutes=None,
        confidence_score=0.72,
        confidence_level="medium",
        reasons=[{"category": "water_balance", "message": "Depleção: 12mm"}],
        rootzone_depletion_mm=12.0,
        rootzone_taw_mm=90.0,
        rootzone_raw_mm=54.0,
        rootzone_swc=0.22,
        today_et0_mm=4.1,
        today_temp_max_c=28.0,
        rainfall_last_24h_mm=0.0,
        forecast_rain_next_48h_mm=2.0,
        last_irrigation_date=None,
        total_irrigation_7d_mm=0.0,
        active_alerts=[],
        generated_at="2026-04-08T08:00:00+00:00",
    )
    defaults.update(overrides)
    return SectorAssistantContext(**defaults)


def _farm_ctx() -> FarmAssistantContext:
    return FarmAssistantContext(
        farm_id="farm-001",
        farm_name="Quinta",
        date="2026-04-08",
        location={"lat": 38.5, "lon": -8.1, "region": "Alentejo"},
        weather_summary={"et0_mm": 4.1, "rainfall_mm": 0.0},
        sectors=[_sector_ctx()],
        total_active_alerts=0,
        missing_data_priorities=["irrigation system not configured"],
        setup_completion_pct=0.0,
    )


@pytest.fixture
def mock_builder():
    builder = MagicMock(spec=AssistantContextBuilder)
    builder.build_sector_context = AsyncMock(return_value=_sector_ctx())
    builder.build_farm_context = AsyncMock(return_value=_farm_ctx())
    builder.to_json = AssistantContextBuilder().to_json  # use real serialiser
    return builder


@pytest.fixture
def assistant(mock_builder):
    return IrrigationAssistant(
        context_builder=mock_builder,
        client=MockChatClient(),
        language="pt",
    )


@pytest.mark.asyncio
async def test_explain_recommendation_returns_nonempty(assistant):
    db = AsyncMock()
    result = await assistant.explain_recommendation("sec-001", db)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_explain_recommendation_no_rec_returns_message(mock_builder):
    mock_builder.build_sector_context = AsyncMock(
        return_value=_sector_ctx(recommendation_action=None)
    )
    asst = IrrigationAssistant(mock_builder, MockChatClient(), "pt")
    db = AsyncMock()
    result = await asst.explain_recommendation("sec-001", db)
    assert "recomendação" in result.lower()


@pytest.mark.asyncio
async def test_summarize_farm_returns_nonempty(assistant):
    db = AsyncMock()
    result = await assistant.summarize_farm("farm-001", db)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_generate_missing_data_questions_returns_list(assistant):
    db = AsyncMock()
    result = await assistant.generate_missing_data_questions("farm-001", db)
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(q, str) for q in result)


@pytest.mark.asyncio
async def test_chat_returns_nonempty(assistant):
    db = AsyncMock()
    result = await assistant.chat("farm-001", "Quando devo regar?", db)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_chat_with_sector_id_uses_sector_context(mock_builder, assistant):
    db = AsyncMock()
    await assistant.chat("farm-001", "Explica a recomendação", db, sector_id="sec-001")
    mock_builder.build_sector_context.assert_called_once_with("sec-001", db)
    mock_builder.build_farm_context.assert_not_called()


@pytest.mark.asyncio
async def test_chat_without_sector_id_uses_farm_context(mock_builder, assistant):
    db = AsyncMock()
    await assistant.chat("farm-001", "Resume a exploração", db, sector_id=None)
    mock_builder.build_farm_context.assert_called_once_with("farm-001", db)
    mock_builder.build_sector_context.assert_not_called()
