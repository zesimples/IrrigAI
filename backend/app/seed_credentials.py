"""Credential resolution for the DB seeder.

Why this exists: `make seed` clears and recreates the demo farms, including their
`FarmCredentials` rows. The Conqueiros credential baked into seed.py carries a
visually-identical `I`/`l` typo in the `client_id`; a re-seed therefore silently
reverted a manually-corrected production credential and re-triggered the
MyIrrigation 406 "Client Signature Invalid" outage.

`resolve_seed_credentials` enforces a precedence that makes re-seeding safe:

  1. existing  — values already stored for the farm (e.g. a prior manual fix via
                 scripts/set_farm_credentials.py). Preserved verbatim; wins over
                 everything else, so a re-seed can never clobber a real credential.
  2. env       — {env_prefix}{FIELD} variables (FIELD uppercased), used only on a
                 fresh seed. Lets prod supply real secrets without committing them.
  3. defaults  — the baked dev/demo fallback, used only when neither above applies.
"""

from __future__ import annotations

from collections.abc import Mapping

CRED_FIELDS = ("username", "password", "client_id", "client_secret", "weather_device_id")


def resolve_seed_credentials(
    existing: Mapping[str, str | None] | None,
    defaults: Mapping[str, str | None],
    env: Mapping[str, str] | None = None,
    env_prefix: str = "",
) -> dict[str, str | None]:
    """Return the credential field values to seed for a farm (see module docstring)."""
    if existing is not None:
        # A credential row already exists — never overwrite it on re-seed.
        return {field: existing.get(field) for field in CRED_FIELDS}

    env = env or {}
    return {
        field: env.get(f"{env_prefix}{field.upper()}") or defaults.get(field)
        for field in CRED_FIELDS
    }
