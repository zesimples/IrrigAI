"""Tests for the chat tool registry/executor (no network, no LLM)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.ai.tools import TOOL_SPECS, ToolScope, execute_tool


def test_tool_specs_shape():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert "get_sector_status" in names
    assert "get_outcomes" in names
    assert "get_calibration_status" in names
    assert "get_recommendation_history" in names
    assert "get_flowmeter_summary" in names
    assert "get_stress_projection" in names
    assert "propose_override" in names
    for t in TOOL_SPECS:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


@pytest.mark.asyncio
async def test_read_tool_access_denied_returns_error():
    access = AsyncMock()
    access.sector_in_farm.side_effect = HTTPException(status_code=404)
    db = AsyncMock()
    out = await execute_tool(
        "get_sector_status",
        {"sector_id": "foreign"},
        access=access,
        db=db,
        scope=ToolScope(farm_id="f1", sector_id=None),
    )
    assert out == {"error": "not_found_or_forbidden"}


@pytest.mark.asyncio
async def test_sector_status_returns_actionable_recommendation_identity(monkeypatch):
    context = SimpleNamespace(
        sector_id="sec-1",
        sector_name="Norte",
        crop_type="olive",
        recommendation_id="rec-123",
        recommendation_action="irrigate",
        recommendation_is_accepted=None,
        irrigation_depth_mm=12.0,
        rootzone_depletion_mm=20.0,
        rootzone_taw_mm=80.0,
        confidence_level="high",
        source_confidence="fresh",
        data_quality_explanation="Leituras atuais.",
        reasons=[],
        active_alerts=[],
        generated_at="2026-07-17T08:00:00+00:00",
    )
    monkeypatch.setattr(
        "app.ai.tools.AssistantContextBuilder.build_sector_context",
        AsyncMock(return_value=context),
    )
    access = AsyncMock()

    out = await execute_tool(
        "get_sector_status",
        {},
        access=access,
        db=AsyncMock(),
        scope=ToolScope(farm_id="farm-1", sector_id="sec-1"),
    )

    access.sector_in_farm.assert_awaited_once_with("sec-1", "farm-1")
    assert out["recommendation_id"] == "rec-123"
    assert out["generated_at"] == "2026-07-17T08:00:00+00:00"
    assert out["is_accepted"] is None


@pytest.mark.asyncio
async def test_propose_override_no_mutation_and_validates_access():
    access = AsyncMock()
    access.recommendation.return_value = object()  # ownership ok
    db = AsyncMock()
    out = await execute_tool(
        "propose_override",
        {"recommendation_id": "rec-1", "depth_mm": 15, "reason": "campo seco"},
        access=access,
        db=db,
        scope=ToolScope(farm_id="f1", sector_id="sec-1"),
    )
    assert out["status"] == "awaiting_confirmation"
    pa = out["proposed_action"]
    assert pa["type"] == "override_recommendation"
    assert pa["recommendation_id"] == "rec-1"
    assert pa["params"]["custom_depth_mm"] == 15
    db.commit.assert_not_called()  # propose-only: never writes


@pytest.mark.asyncio
async def test_propose_override_access_denied_returns_error():
    access = AsyncMock()
    access.recommendation.side_effect = HTTPException(status_code=404)
    db = AsyncMock()
    out = await execute_tool(
        "propose_override",
        {"recommendation_id": "foreign", "depth_mm": 15, "reason": "x"},
        access=access,
        db=db,
        scope=ToolScope(farm_id="f1", sector_id="sec-1"),
    )
    assert out == {"error": "not_found_or_forbidden"}
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_propose_run_calibration_uses_scope_sector():
    access = AsyncMock()
    access.sector.return_value = object()
    db = AsyncMock()
    out = await execute_tool(
        "propose_run_calibration",
        {},
        access=access,
        db=db,
        scope=ToolScope(farm_id="f1", sector_id="sec-9"),
    )
    assert out["proposed_action"]["type"] == "run_calibration"
    assert out["proposed_action"]["sector_id"] == "sec-9"
    db.commit.assert_not_called()
