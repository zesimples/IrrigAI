"""Redis-backed distributed job lock.

Prevents the same scheduled job from running concurrently if the worker
process is restarted mid-job or (in a future multi-replica setup) if two
instances race to fire the same trigger.

Usage:
    async with JobLock("data_ingestion", ttl=900) as acquired:
        if not acquired:
            return
        # ... do work

The lock is released explicitly on clean exit, or expires after ttl seconds
if the process dies — no manual cleanup required.
"""

import logging

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    return _redis


class JobLock:
    def __init__(self, job_id: str, ttl: int) -> None:
        self._key = f"job_lock:{job_id}"
        self._ttl = ttl
        self._acquired = False

    async def __aenter__(self) -> bool:
        r = _get_redis()
        self._acquired = bool(await r.set(self._key, "1", nx=True, ex=self._ttl))
        if not self._acquired:
            logger.info("Job already running, skipping: %s", self._key)
        return self._acquired

    async def __aexit__(self, *_) -> None:
        if self._acquired:
            await _get_redis().delete(self._key)
            self._acquired = False
