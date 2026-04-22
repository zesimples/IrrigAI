"""Shared slowapi rate limiter instance.

Backed by Redis so limits are shared across all uvicorn workers.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.REDIS_URL,
)
