"""Chat endpoint integration tests (mock LLM provider)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_agent import ChatAgent
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient
from app.api.v1.chat import get_chat_agent
from app.main import app
from app.models import (
    AIResponseFeedback,
    ChatConversation,
    ChatMessage,
    Farm,
    Plot,
    Sector,
    User,
)
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"  # matches the authenticated `client` fixture


def _mock_chat_agent() -> ChatAgent:
    return ChatAgent(
        client=MockChatClient(),
        context_builder=AssistantContextBuilder(),
        language="pt",
    )


@pytest.fixture(autouse=True)
def override_chat_agent():
    """Force mock LLM for all tests in this module regardless of env settings."""
    app.dependency_overrides[get_chat_agent] = _mock_chat_agent
    yield
    app.dependency_overrides.pop(get_chat_agent, None)


@pytest.fixture
async def chat_farm(db: AsyncSession):
    owner = (await db.execute(select(User).where(User.email == _OWNER_EMAIL))).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    farm = Farm(name="Chat Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Chat Sector", crop_type="almond")
    db.add(sector)
    await db.commit()
    yield {"farm_id": farm.id, "sector_id": sector.id}
    await delete_farm_subtree(db, farm.id)


@pytest.mark.asyncio
async def test_chat_returns_prose_reply(client, chat_farm):
    resp = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={"message": "Quanto choveu esta semana?", "history": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"]
    assert body["proposed_action"] is None
    assert body["conversation_id"]
    assert body["message_id"]

    conversation = await client.get(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat/conversations/{body['conversation_id']}"
    )
    assert conversation.status_code == 200
    assert [row["role"] for row in conversation.json()["messages"]] == [
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_chat_accepts_history(client, chat_farm):
    resp = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={
            "message": "e agora?",
            "history": [
                {"role": "user", "content": "olá"},
                {"role": "assistant", "content": "olá, em que posso ajudar?"},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["reply"]


@pytest.mark.asyncio
async def test_chat_resumes_server_side_history(client, chat_farm, db):
    first = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={"message": "primeira pergunta"},
    )
    conversation_id = first.json()["conversation_id"]

    second = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={
            "message": "e agora?",
            "conversation_id": conversation_id,
        },
    )

    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    stored = (
        (
            await db.execute(
                select(ChatMessage)
                .join(
                    ChatConversation,
                    ChatMessage.conversation_id == ChatConversation.id,
                )
                .where(ChatConversation.id == conversation_id)
                .order_by(ChatMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [row.role for row in stored] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_chat_conversation_can_be_deleted(client, chat_farm):
    chat = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={"message": "conversa descartável"},
    )
    conversation_id = chat.json()["conversation_id"]

    deleted = await client.delete(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat/conversations/{conversation_id}"
    )
    fetched = await client.get(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat/conversations/{conversation_id}"
    )

    assert deleted.status_code == 204
    assert fetched.status_code == 404


@pytest.mark.asyncio
async def test_chat_stream_returns_sse_and_persists_message(client, chat_farm):
    response = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat/stream",
        json={"message": "estado do sector?", "sector_id": chat_farm["sector_id"]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: conversation" in response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text


@pytest.mark.asyncio
async def test_field_observation_crud_is_sector_scoped(client, chat_farm):
    created = await client.post(
        f"/api/v1/sectors/{chat_farm['sector_id']}/field-observations",
        json={
            "observation_type": "field_check",
            "structured_value": {"visual_soil_condition": "dry"},
            "text": "Folhas ligeiramente enroladas.",
        },
    )
    assert created.status_code == 201
    observation = created.json()
    assert observation["is_verified"] is False

    verified = await client.patch(
        f"/api/v1/field-observations/{observation['id']}/verification",
        json={"is_verified": True},
    )
    assert verified.status_code == 200
    assert verified.json()["is_verified"] is True

    listed = await client.get(f"/api/v1/sectors/{chat_farm['sector_id']}/field-observations")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [observation["id"]]


@pytest.mark.asyncio
async def test_chat_feedback_is_persisted_for_owned_message(client, chat_farm):
    chat = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={"message": "resumo"},
    )
    response = await client.post(
        "/api/v1/ai/feedback",
        json={
            "surface": "chat",
            "rating": 1,
            "farm_id": chat_farm["farm_id"],
            "chat_message_id": chat.json()["message_id"],
        },
    )
    assert response.status_code == 201
    assert response.json()["rating"] == 1


@pytest.mark.asyncio
async def test_chat_feedback_is_one_mutable_vote_per_message(client, chat_farm, db):
    chat = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={"message": "resumo"},
    )
    message_id = chat.json()["message_id"]

    up = await client.post(
        "/api/v1/ai/feedback",
        json={"surface": "chat", "rating": 1, "chat_message_id": message_id},
    )
    assert up.status_code == 201
    down = await client.post(
        "/api/v1/ai/feedback",
        json={"surface": "chat", "rating": -1, "chat_message_id": message_id},
    )
    assert down.status_code in (200, 201)

    rows = (
        (
            await db.execute(
                select(AIResponseFeedback).where(
                    AIResponseFeedback.chat_message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].rating == -1
