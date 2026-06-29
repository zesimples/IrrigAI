"""Tests for the agentic chat layer (schemas, tools, ChatAgent)."""

from __future__ import annotations

import pytest

from app.schemas.ai import ChatTurn, ProposedAction


def test_chat_turn_rejects_bad_role():
    with pytest.raises(Exception):
        ChatTurn(role="system", content="x")


def test_proposed_action_minimal():
    a = ProposedAction(type="run_calibration", summary="Calibrar setor", sector_id="sec-1")
    assert a.type == "run_calibration"
    assert a.params == {}
