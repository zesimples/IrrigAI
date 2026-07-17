"""Tests for the agentic chat layer (schemas, tools, ChatAgent)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.ai.chat_agent import MAX_HISTORY_TURNS, ChatAgent
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient
from app.schemas.ai import ChatTurn, ProposedAction


def test_chat_turn_rejects_bad_role():
    with pytest.raises(ValidationError):
        ChatTurn(role="system", content="x")


def test_proposed_action_minimal():
    a = ProposedAction(type="run_calibration", summary="Calibrar setor", sector_id="sec-1")
    assert a.type == "run_calibration"
    assert a.params == {}

def _agent():
    return ChatAgent(
        client=MockChatClient(),
        context_builder=AssistantContextBuilder(),
        language="pt",
    )


@pytest.mark.asyncio
async def test_chat_agent_prose_reply(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_seed_scope_context", AsyncMock(return_value={}))
    access = AsyncMock()
    db = AsyncMock()
    result = await agent.run(
        farm_id="f1", sector_id=None, message="Quanto choveu esta semana?",
        history=[], access=access, db=db,
    )
    assert result.proposed_action is None
    assert result.reply


@pytest.mark.asyncio
async def test_chat_agent_propose_calibration(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_seed_scope_context", AsyncMock(return_value={}))
    access = AsyncMock()
    access.sector.return_value = object()
    db = AsyncMock()
    result = await agent.run(
        farm_id="f1", sector_id="sec-9", message="Podes recalibrar este setor?",
        history=[], access=access, db=db,
    )
    assert result.proposed_action is not None
    assert result.proposed_action.type == "run_calibration"
    assert result.proposed_action.sector_id == "sec-9"
    assert result.reply  # model writes a prose summary after proposing
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_chat_agent_accepts_current_recommendation_from_tool_output(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_seed_scope_context", AsyncMock(return_value={}))
    calls: list[str] = []

    async def fake_execute(name, args, **kwargs):
        calls.append(name)
        if name == "get_sector_status":
            return {
                "sector_id": "sec-9",
                "recommendation_id": "rec-current",
                "action": "irrigate",
            }
        if name == "propose_accept_recommendation":
            assert args["recommendation_id"] == "rec-current"
            return {
                "status": "awaiting_confirmation",
                "proposed_action": {
                    "type": "accept_recommendation",
                    "summary": "Aceitar a recomendação atual.",
                    "sector_id": "sec-9",
                    "recommendation_id": "rec-current",
                    "params": {},
                },
            }
        raise AssertionError(name)

    monkeypatch.setattr("app.ai.chat_agent.execute_tool", fake_execute)
    result = await agent.run(
        farm_id="farm-1",
        sector_id="sec-9",
        message="Aceita a recomendação atual",
        history=[],
        access=AsyncMock(),
        db=AsyncMock(),
    )

    assert calls == ["get_sector_status", "propose_accept_recommendation"]
    assert result.proposed_action is not None
    assert result.proposed_action.recommendation_id == "rec-current"


@pytest.mark.asyncio
async def test_chat_agent_trims_history(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_seed_scope_context", AsyncMock(return_value={}))
    captured = {}

    async def fake_loop(messages, tools, **kw):
        captured["messages"] = messages
        from app.ai.openai_client import LLMToolResponse
        return LLMToolResponse(content="ok", tool_calls=[])

    monkeypatch.setattr(agent.client, "run_tool_loop", fake_loop)
    history = [ChatTurn(role="user", content=f"m{i}") for i in range(20)]
    await agent.run(
        farm_id="f1", sector_id=None, message="agora", history=history,
        access=AsyncMock(), db=AsyncMock(),
    )
    # system + <=8 history + current user
    assert len(captured["messages"]) <= 1 + MAX_HISTORY_TURNS + 1
