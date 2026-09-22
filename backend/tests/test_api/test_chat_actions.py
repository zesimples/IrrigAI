"""A0/A2 regressions for the proposed-action lifecycle.

Before A2 a proposal lived only in one assistant message's JSON: reopening the
conversation re-offered a completed action, a retried confirmation executed the
write twice, and a failure rendered exactly like a success.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_agent import ChatAgent
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient
from app.api.v1.chat import get_chat_agent
from app.core.enums import ConfidenceLevel, RecommendationAction
from app.main import app
from app.models import (
    ChatAction,
    ChatMessage,
    Farm,
    Plot,
    Recommendation,
    Sector,
    User,
)
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"


@pytest.mark.asyncio
@pytest.mark.parametrize("action_type", ["accept_recommendation", "regenerate_recommendation"])
async def test_result_event_failure_rolls_back_the_mutation(
    client, db, action_farm, monkeypatch, action_type
):
    from app.services import chat_actions

    _, action_id = await _propose(client, db, action_farm, action_type=action_type)
    before = set(
        (
            await db.execute(
                select(Recommendation.id).where(
                    Recommendation.sector_id == action_farm["sector_id"]
                )
            )
        ).scalars()
    )

    async def fail_event(*args):
        raise RuntimeError("private database details must not escape")

    monkeypatch.setattr(chat_actions, "_record_result_event", fail_event)
    response = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )
    assert response.json()["status"] == "failed"
    assert "private database" not in response.text
    db.expire_all()
    after = set(
        (
            await db.execute(
                select(Recommendation.id).where(
                    Recommendation.sector_id == action_farm["sector_id"]
                )
            )
        ).scalars()
    )
    assert before == after
    rec = await db.get(Recommendation, action_farm["recommendation_id"])
    assert rec.is_accepted is not True


@pytest.mark.asyncio
@pytest.mark.parametrize("competitor", ["confirm", "cancel"])
async def test_concurrent_action_cannot_overwrite_success(
    client, db, action_farm, monkeypatch, competitor
):
    from app.services import chat_actions

    _, action_id = await _propose(client, db, action_farm)
    entered, release = asyncio.Event(), asyncio.Event()
    original = chat_actions._execute
    executions = []

    async def delayed(action, **kwargs):
        executions.append(action.id)
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=10)
        return await original(action, **kwargs)

    monkeypatch.setattr(chat_actions, "_execute", delayed)
    url = f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}"
    first = asyncio.create_task(client.post(f"{url}/confirm"))
    await asyncio.wait_for(entered.wait(), timeout=10)
    second = asyncio.create_task(client.post(f"{url}/{competitor}"))
    try:
        # Let the second request reach its independent DB transaction while the
        # first holds the action lock; it must wait for the committed outcome.
        await asyncio.sleep(0.1)
    finally:
        release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    assert results[0].json()["status"] == "succeeded"
    assert results[1].status_code == (200 if competitor == "confirm" else 409)
    assert executions == [action_id]
    db.expire_all()
    assert (await db.get(ChatAction, action_id)).status == "succeeded"


@pytest.fixture(autouse=True)
def override_chat_agent():
    app.dependency_overrides[get_chat_agent] = lambda: ChatAgent(
        client=MockChatClient(),
        context_builder=AssistantContextBuilder(),
        language="pt",
    )
    yield
    app.dependency_overrides.pop(get_chat_agent, None)


@pytest.fixture
async def action_farm(db: AsyncSession):
    owner = (await db.execute(select(User).where(User.email == _OWNER_EMAIL))).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    farm = Farm(name="Action Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.30, wilting_point=0.14)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Action Sector", crop_type="olive")
    db.add(sector)
    await db.flush()
    rec = Recommendation(
        sector_id=sector.id,
        generated_at=datetime.now(UTC),
        target_date=datetime.now(UTC).date(),
        action=RecommendationAction.IRRIGATE,
        irrigation_depth_mm=12.0,
        confidence_score=0.8,
        confidence_level=ConfidenceLevel.HIGH,
        inputs_snapshot={},
    )
    db.add(rec)
    await db.commit()
    # Bind the ids now: tests call db.expire_all() to see committed API writes, and
    # a later attribute read on an expired instance would trip MissingGreenlet.
    ids = {
        "farm_id": farm.id,
        "sector_id": sector.id,
        "recommendation_id": rec.id,
        "user_id": owner.id,
    }
    yield ids
    await delete_farm_subtree(db, ids["farm_id"])


async def _propose(client, db, action_farm, *, action_type="accept_recommendation"):
    """Create a conversation and attach a pending action to its assistant turn."""
    chat = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat",
        json={"message": "estado", "sector_id": action_farm["sector_id"]},
    )
    body = chat.json()
    message = await db.get(ChatMessage, body["message_id"])
    message.proposed_action = {
        "type": action_type,
        "summary": "Aceitar a recomendação atual.",
        "sector_id": action_farm["sector_id"],
        "recommendation_id": action_farm["recommendation_id"],
        "params": {},
    }
    row = ChatAction(
        conversation_id=body["conversation_id"],
        chat_message_id=body["message_id"],
        user_id=action_farm["user_id"],
        farm_id=action_farm["farm_id"],
        sector_id=action_farm["sector_id"],
        recommendation_id=action_farm["recommendation_id"],
        action_type=action_type,
        summary="Aceitar a recomendação atual.",
        params={},
        status="pending",
        idempotency_key=f"test-{body['message_id']}",
    )
    db.add(row)
    await db.commit()
    return body, row.id


@pytest.mark.asyncio
async def test_confirm_executes_once_and_records_the_result(client, db, action_farm):
    body, action_id = await _propose(client, db, action_farm)

    confirmed = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )

    assert confirmed.status_code == 200
    payload = confirmed.json()
    assert payload["status"] == "succeeded"
    assert payload["result"]

    rec = await db.get(Recommendation, action_farm["recommendation_id"])
    await db.refresh(rec)
    assert rec.is_accepted is True


@pytest.mark.asyncio
async def test_repeated_confirmation_does_not_write_twice(client, db, action_farm):
    body, action_id = await _propose(client, db, action_farm, action_type="reject_recommendation")

    first = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )
    second = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )

    assert first.json()["status"] == "succeeded"
    assert second.status_code == 200
    assert second.json()["status"] == "succeeded"
    # The same server identity, not a second action.
    assert second.json()["id"] == first.json()["id"]
    db.expire_all()
    rows = (await db.execute(select(ChatAction).where(ChatAction.id == action_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "succeeded"


@pytest.mark.asyncio
async def test_a_superseded_recommendation_invalidates_the_proposal(client, db, action_farm):
    body, action_id = await _propose(client, db, action_farm)
    newer = Recommendation(
        sector_id=action_farm["sector_id"],
        generated_at=datetime.now(UTC) + timedelta(minutes=5),
        target_date=datetime.now(UTC).date(),
        action=RecommendationAction.SKIP,
        confidence_score=0.7,
        confidence_level=ConfidenceLevel.MEDIUM,
        inputs_snapshot={},
    )
    db.add(newer)
    await db.commit()

    response = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )

    assert response.status_code == 409
    assert response.json()["status"] == "invalidated"
    db.expire_all()
    stored = await db.get(ChatAction, action_id)
    assert stored.status == "invalidated"


@pytest.mark.asyncio
async def test_cancel_is_terminal_and_survives_reopen(client, db, action_farm):
    body, action_id = await _propose(client, db, action_farm)

    cancelled = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/cancel"
    )
    assert cancelled.json()["status"] == "cancelled"

    confirm_after_cancel = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )
    assert confirm_after_cancel.status_code == 409

    detail = await client.get(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/conversations/{body['conversation_id']}"
    )
    proposals = [
        message["proposed_action"]
        for message in detail.json()["messages"]
        if message.get("proposed_action")
    ]
    assert proposals and proposals[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_a_failed_action_is_not_shown_as_completed(client, db, action_farm):
    """A run_calibration on a sector with no probe fails; it must say so."""
    body, action_id = await _propose(client, db, action_farm, action_type="run_calibration")

    response = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )

    assert response.status_code in (200, 422)
    assert response.json()["status"] == "failed"
    db.expire_all()
    stored = await db.get(ChatAction, action_id)
    assert stored.status == "failed"
    assert stored.error_detail


@pytest.mark.asyncio
async def test_action_result_is_persisted_as_a_conversation_event(client, db, action_farm):
    body, action_id = await _propose(client, db, action_farm)

    await client.post(f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm")

    messages = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == body["conversation_id"])
                .order_by(ChatMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert any(message.surface == "action_result" for message in messages)


@pytest.mark.asyncio
async def test_another_users_action_is_not_found(client, db, action_farm):
    body, action_id = await _propose(client, db, action_farm)
    stored = await db.get(ChatAction, action_id)
    stranger = User(email="stranger-actions@irrigai.dev", name="S", hashed_password="x")
    db.add(stranger)
    await db.flush()
    stored.user_id = stranger.id
    await db.commit()

    response = await client.post(
        f"/api/v1/farms/{action_farm['farm_id']}/chat/actions/{action_id}/confirm"
    )
    assert response.status_code == 404
    await db.delete(stranger)
    await db.commit()
