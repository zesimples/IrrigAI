"""Redis-backed AI quota and response-cache helpers."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config import get_settings
from app.schemas.ai import AgronomicInterpretation

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            get_settings().REDIS_URL,
            decode_responses=True,
        )
    return _redis


async def consume_daily_ai_quota(user_id: str) -> None:
    settings = get_settings()
    limit = settings.LLM_DAILY_REQUEST_LIMIT
    if settings.LLM_PROVIDER == "mock" or limit <= 0:
        return
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    key = f"ai:quota:{user_id}:{day}"
    try:
        count = await _get_redis().incr(key)
        if count == 1:
            await _get_redis().expire(key, 172800)
    except Exception:
        logger.warning("Redis AI quota check failed; allowing request", exc_info=True)
        return
    if count > limit:
        raise HTTPException(
            429,
            detail=(
                "Limite diário do assistente atingido. Tente novamente após a renovação do limite."
            ),
        )


def context_digest(context: dict) -> str:
    payload = json.dumps(
        context,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def get_cached_interpretation(
    *,
    surface: str,
    entity_id: str,
    digest: str,
) -> AgronomicInterpretation | None:
    key = f"ai:response:{surface}:{entity_id}:{digest}"
    try:
        value = await _get_redis().get(key)
        return AgronomicInterpretation.model_validate_json(value) if value else None
    except Exception:
        logger.warning("Redis AI response cache read failed", exc_info=True)
        return None


async def set_cached_interpretation(
    *,
    surface: str,
    entity_id: str,
    digest: str,
    interpretation: AgronomicInterpretation,
) -> None:
    key = f"ai:response:{surface}:{entity_id}:{digest}"
    try:
        await _get_redis().set(
            key,
            interpretation.model_dump_json(),
            ex=get_settings().LLM_FARM_SUMMARY_CACHE_TTL_SECONDS,
        )
    except Exception:
        logger.warning("Redis AI response cache write failed", exc_info=True)
