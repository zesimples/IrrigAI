"""Unit tests for seed credential resolution.

Regression context: a `make seed` run overwrote a manually-corrected Conqueiros
MyIrrigation credential (fixed via scripts/set_farm_credentials.py) with the
typo'd `client_id` baked into seed.py, re-triggering the 406 "Client Signature
Invalid" outage. resolve_seed_credentials() must never let a re-seed clobber an
existing stored credential.
"""

from app.seed_credentials import resolve_seed_credentials

_DEFAULTS = {
    "username": "conqueiros_api",
    "password": "conqueiros_api",
    "client_id": "YYRIcSNREmmcFwNbt1i02w",  # the typo'd (capital I) baked default
    "client_secret": "BTF77w9Yf6gUjabINuiFRA",
    "weather_device_id": "824",
}


def test_preserves_existing_credentials_over_baked_defaults():
    """A credential row already stored for the farm (a prior manual fix) wins."""
    existing = {
        "username": "conqueiros_api",
        "password": "conqueiros_api",
        "client_id": "YYRlcSNREmmcFwNbt1i02w",  # the GOOD value (lowercase l)
        "client_secret": "BTF77w9Yf6gUjabINuiFRA",
        "weather_device_id": "824",
    }

    resolved = resolve_seed_credentials(existing, _DEFAULTS)

    assert resolved["client_id"] == "YYRlcSNREmmcFwNbt1i02w"
    assert resolved == existing


def test_existing_wins_even_when_env_override_is_set():
    existing = {**_DEFAULTS, "client_id": "manually-fixed-id"}
    env = {"SEED_CONQUEIROS_CLIENT_ID": "env-id"}

    resolved = resolve_seed_credentials(
        existing, _DEFAULTS, env=env, env_prefix="SEED_CONQUEIROS_"
    )

    assert resolved["client_id"] == "manually-fixed-id"


def test_uses_env_override_on_fresh_seed():
    """No existing row → env vars take precedence over baked defaults."""
    env = {
        "SEED_CONQUEIROS_CLIENT_ID": "real-id-from-env",
        "SEED_CONQUEIROS_CLIENT_SECRET": "real-secret-from-env",
    }

    resolved = resolve_seed_credentials(
        None, _DEFAULTS, env=env, env_prefix="SEED_CONQUEIROS_"
    )

    assert resolved["client_id"] == "real-id-from-env"
    assert resolved["client_secret"] == "real-secret-from-env"
    # untouched fields fall back to defaults
    assert resolved["weather_device_id"] == "824"


def test_falls_back_to_defaults_when_no_existing_and_no_env():
    resolved = resolve_seed_credentials(None, _DEFAULTS, env={}, env_prefix="SEED_CONQUEIROS_")

    assert resolved == _DEFAULTS


# --- _existing_cred_values: snapshot a farm's creds before a re-seed delete ---


def test_existing_cred_values_returns_none_when_farm_absent():
    from app.seed import _existing_cred_values

    assert _existing_cred_values(None) is None


def test_existing_cred_values_returns_none_when_no_credential_row():
    from app.models import Farm
    from app.seed import _existing_cred_values

    assert _existing_cred_values(Farm(name="x", credentials=None)) is None


def test_existing_cred_values_snapshots_stored_credentials():
    from app.models import Farm, FarmCredentials
    from app.seed import _existing_cred_values

    farm = Farm(
        name="Herdade dos Conqueiros",
        credentials=FarmCredentials(
            username="conqueiros_api",
            password="conqueiros_api",
            client_id="YYRlcSNREmmcFwNbt1i02w",  # the good (manually-fixed) value
            client_secret="BTF77w9Yf6gUjabINuiFRA",
            weather_device_id="824",
        ),
    )

    snapshot = _existing_cred_values(farm)

    assert snapshot["client_id"] == "YYRlcSNREmmcFwNbt1i02w"
    # round-trips through resolve_seed_credentials → preserved over baked defaults
    assert resolve_seed_credentials(snapshot, _DEFAULTS)["client_id"] == "YYRlcSNREmmcFwNbt1i02w"
