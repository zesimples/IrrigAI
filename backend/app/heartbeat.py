"""Scheduler liveness heartbeat (Redis-backed).

The worker container has no HTTP server, so its Docker healthcheck cannot hit
``/health``. Instead the scheduler stamps a Redis key on startup and after every
job tick; the healthcheck (``python -m app.worker_health``) reads the key and
fails when it goes stale — i.e. the scheduler thread has hung even though the
process is technically alive.
"""

from __future__ import annotations

import logging
import time

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "scheduler:heartbeat"
# The most frequent job runs every 15 min; allow a couple of missed ticks before
# declaring the scheduler dead so a single slow run doesn't flap the container.
STALE_THRESHOLD_SECONDS = 1800

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    return _client


def record_heartbeat() -> None:
    """Stamp the current time. Best-effort: a Redis hiccup must not kill a job."""
    try:
        _redis().set(HEARTBEAT_KEY, str(int(time.time())))
    except Exception:
        logger.warning("Failed to record scheduler heartbeat", exc_info=True)


def heartbeat_age_seconds() -> float | None:
    """Seconds since the last heartbeat, or None if never stamped."""
    value = _redis().get(HEARTBEAT_KEY)
    if value is None:
        return None
    return time.time() - float(value)
