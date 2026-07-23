from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.schemas.ai import AgronomicInterpretation
from app.services import ai_runtime


class FakeRedis:
    def __init__(self, count: int = 1):
        self.count = count
        self.values: dict[str, str] = {}

    async def incr(self, key):
        return self.count

    async def expire(self, key, seconds):
        return True

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.values[key] = value
        return True


@pytest.mark.asyncio
async def test_daily_ai_quota_rejects_requests_over_limit(monkeypatch):
    monkeypatch.setattr(
        ai_runtime,
        "get_settings",
        lambda: SimpleNamespace(
            LLM_PROVIDER="openai",
            LLM_DAILY_REQUEST_LIMIT=2,
        ),
    )
    monkeypatch.setattr(ai_runtime, "_get_redis", lambda: FakeRedis(count=3))

    with pytest.raises(HTTPException) as exc:
        await ai_runtime.consume_daily_ai_quota("user-1")

    assert exc.value.status_code == 429


def test_context_digest_is_stable_across_key_order():
    assert ai_runtime.context_digest({"a": 1, "b": 2}) == ai_runtime.context_digest(
        {"b": 2, "a": 1}
    )


@pytest.mark.asyncio
async def test_ai_response_cache_round_trips_structured_result(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ai_runtime, "_get_redis", lambda: redis)
    monkeypatch.setattr(
        ai_runtime,
        "get_settings",
        lambda: SimpleNamespace(LLM_FARM_SUMMARY_CACHE_TTL_SECONDS=900),
    )
    result = AgronomicInterpretation(
        summary="Resumo",
        risk_level="low",
        irrigation_advice="Não regar.",
        evidence=[],
        confidence_score=0.8,
        confidence_explanation="Dados actuais.",
    )

    await ai_runtime.set_cached_interpretation(
        surface="farm_summary",
        entity_id="farm-1",
        digest="digest",
        interpretation=result,
    )
    cached = await ai_runtime.get_cached_interpretation(
        surface="farm_summary",
        entity_id="farm-1",
        digest="digest",
    )

    assert cached == result
