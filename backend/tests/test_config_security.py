"""Production security configuration guards.

In production (DEBUG=false) the app must refuse to boot with insecure key
configuration: a missing dedicated ENCRYPTION_KEY (which would silently fall
back to SECRET_KEY, coupling at-rest credential encryption to JWT signing) or
the placeholder default SECRET_KEY.
"""

import pytest

from app.config import Settings, check_production_security


def _settings(**overrides) -> Settings:
    base = dict(
        DEBUG=False,
        SECRET_KEY="a-real-production-secret",
        ENCRYPTION_KEY="a-real-encryption-key",
    )
    base.update(overrides)
    return Settings(**base)


def test_missing_encryption_key_in_production_raises():
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        check_production_security(_settings(ENCRYPTION_KEY=""))


def test_default_secret_key_in_production_raises():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        check_production_security(_settings(SECRET_KEY="change-me-in-production"))


def test_valid_production_config_passes():
    check_production_security(_settings())  # must not raise


def test_debug_mode_allows_insecure_defaults():
    # Local/dev/test convenience: no dedicated key required when DEBUG=true.
    check_production_security(
        _settings(DEBUG=True, ENCRYPTION_KEY="", SECRET_KEY="change-me-in-production")
    )
