"""At-rest field encryption — Fernet (AES-128-CBC + HMAC-SHA256).

Key derivation: SHA-256 of ENCRYPTION_KEY env var (preferred) or SECRET_KEY
fallback. Any string length works; output is a valid 32-byte Fernet key.

EncryptedString is a SQLAlchemy TypeDecorator: columns store ciphertext,
Python attributes always expose plaintext. Decryption failures return None
and log an error rather than raising, so a bad key yields null reads instead
of a 500 crash (still caught in monitoring).
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        from app.config import get_settings
        settings = get_settings()
        key_material = settings.ENCRYPTION_KEY or settings.SECRET_KEY
        if not settings.ENCRYPTION_KEY:
            logger.warning(
                "ENCRYPTION_KEY not set — deriving from SECRET_KEY. "
                "Set a dedicated ENCRYPTION_KEY in .env for production."
            )
        digest = hashlib.sha256(key_material.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        logger.error("Field decryption failed — verify ENCRYPTION_KEY matches the key used to encrypt")
        return None


class EncryptedString(TypeDecorator):
    """Column type that transparently encrypts on write and decrypts on read."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
