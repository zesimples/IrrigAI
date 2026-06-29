"""Chat endpoint integration tests (mock LLM provider)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_agent import ChatAgent
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient
from app.api.v1.chat import get_chat_agent
from app.main import app
from app.models import Farm, Plot, Sector, User
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
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
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
