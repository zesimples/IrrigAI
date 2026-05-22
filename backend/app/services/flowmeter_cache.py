# backend/app/services/flowmeter_cache.py
"""Redis-backed cache for flowmeter AI analysis text.

Caches only the AI text string (not the statistics, which are computed fresh
from DB on every request). Cache key: flowmeter_analysis:{scope}:{id}:{period_days}.
TTL: 7200 s (2 hours). Errors are logged and silently ignored — the endpoint
falls back to a live LLM call if Redis is unavailable.
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

CACHE_TTL = 7200  # 2 hours

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    return _redis


async def get_analysis_cache(scope: str, entity_id: str, period_days: int) -> str | None:
    """Return cached AI text, or None if missing/expired/error."""
    try:
        r = _get_redis()
        key = f"flowmeter_analysis:{scope}:{entity_id}:{period_days}"
        return await r.get(key)
    except Exception:
        logger.warning("Redis get failed for flowmeter_analysis cache — skipping cache")
        return None


async def set_analysis_cache(scope: str, entity_id: str, period_days: int, value: str) -> None:
    """Store AI text in Redis with TTL. Silent on error."""
    try:
        r = _get_redis()
        key = f"flowmeter_analysis:{scope}:{entity_id}:{period_days}"
        await r.set(key, value, ex=CACHE_TTL)
    except Exception:
        logger.warning("Redis set failed for flowmeter_analysis cache — continuing without cache")
