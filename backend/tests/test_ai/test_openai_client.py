"""Tests for OpenAI client wrappers."""

import pytest

from app.ai.openai_client import MockChatClient, OpenAIChatClient, get_chat_client
from app.config import Settings
from app.schemas.ai import AgronomicInterpretation


@pytest.mark.asyncio
async def test_mock_run_tool_loop_prose_by_default():
    client = MockChatClient()
    resp = await client.run_tool_loop(
        messages=[{"role": "user", "content": "Quanto choveu esta semana?"}],
        tools=[],
    )
    assert resp.tool_calls == []
    assert resp.content


@pytest.mark.asyncio
async def test_mock_run_tool_loop_proposes_calibration_on_keyword():
    client = MockChatClient()
    resp = await client.run_tool_loop(
        messages=[{"role": "user", "content": "Podes recalibrar este setor?"}],
        tools=[],
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "propose_run_calibration"


@pytest.mark.asyncio
async def test_mock_run_tool_loop_terminates_after_tool_result():
    client = MockChatClient()
    resp = await client.run_tool_loop(
        messages=[
            {"role": "user", "content": "recalibrar"},
            {"role": "assistant", "content": None},
            {"role": "tool", "tool_call_id": "t1", "content": "{}"},
        ],
        tools=[],
    )
    assert resp.tool_calls == []
    assert resp.content


@pytest.mark.asyncio
async def test_mock_client_returns_nonempty_string():
    client = MockChatClient()
    result = await client.complete(
        system_prompt="Contexto de irrigar o setor",
        user_message="Explica a recomendação",
    )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_mock_client_irrigation_context():
    client = MockChatClient()
    result = await client.complete(
        system_prompt="Recomendação: irrigar o setor amanhã",
        user_message="Porquê devo irrigar?",
    )
    assert "rega" in result.lower() or "regar" in result.lower()


@pytest.mark.asyncio
async def test_mock_client_missing_context():
    client = MockChatClient()
    result = await client.complete(
        system_prompt="Configuração em falta no sector",
        user_message="O que falta configurar?",
    )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_mock_client_summary_context():
    client = MockChatClient()
    result = await client.complete(
        system_prompt="Resumo da exploração agrícola",
        user_message="Faz um resumo do estado da exploração",
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_chat_client_returns_mock_when_configured():
    settings = Settings(LLM_PROVIDER="mock")
    client = get_chat_client(settings)
    assert isinstance(client, MockChatClient)


def test_get_chat_client_raises_without_api_key():
    settings = Settings(LLM_PROVIDER="openai", OPENAI_API_KEY="")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        get_chat_client(settings)


def test_get_chat_client_raises_for_unknown_provider():
    # We have to bypass Literal validation via construct
    settings = Settings.model_construct(LLM_PROVIDER="unknown")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_chat_client(settings)


def test_openai_client_routes_models_by_surface():
    settings = Settings(
        LLM_PROVIDER="openai",
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="base-model",
        OPENAI_MODEL_CHAT="chat-model",
        OPENAI_MODEL_STRUCTURED="structured-model",
        OPENAI_MODEL_SUMMARY="summary-model",
    )

    client = get_chat_client(settings)

    assert isinstance(client, OpenAIChatClient)
    assert client.model_for_surface("chat") == "chat-model"
    assert client.model_for_surface("farm_summary") == "summary-model"
    assert client.model_for_surface("probe_diagnosis") == "structured-model"


@pytest.mark.asyncio
async def test_mock_complete_structured_returns_valid_interpretation():
    client = MockChatClient()
    result = await client.complete_structured(
        system_prompt="Interpreta a recomendação de irrigar o setor",
        user_message="Explica",
        schema_model=AgronomicInterpretation,
    )
    assert isinstance(result, AgronomicInterpretation)
    assert result.summary
    assert result.risk_level in ("low", "medium", "high")
    assert 0.0 <= result.confidence_score <= 1.0
