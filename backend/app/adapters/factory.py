"""Adapter factory.

Maps provider names (from .env) to concrete implementations.
Supports per-farm credentials: if a Farm record has a FarmCredentials row,
those override the global .env credentials so two farms can use different accounts.

Per-farm credentials are stored encrypted in the farm_credentials table and
must be eagerly loaded (via selectinload(Farm.credentials)) before passing
the farm object here — lazy loading in async context raises MissingGreenlet.
"""

from app.adapters.base import ProbeDataProvider, WeatherDataProvider
from app.adapters.mock_probe import MockProbeProvider
from app.adapters.mock_weather import MockWeatherProvider
from app.config import Settings

# Cache adapters by a full credential tuple so two farms with different client_ids
# or project scopes never share an adapter instance (and its JWT token).
_irriwatch_instance: "IrriWatchAdapter | None" = None  # type: ignore[name-defined]
_myirrigation_cache: "dict[tuple, MyIrrigationAdapter]" = {}  # type: ignore[name-defined]


def _get_irriwatch(config: Settings):
    """Return a singleton IrriWatchAdapter (shared for probe + weather)."""
    global _irriwatch_instance
    if _irriwatch_instance is None:
        from app.adapters.irriwatch import IrriWatchAdapter
        if not config.IRRIWATCH_CLIENT_ID or not config.IRRIWATCH_CLIENT_SECRET:
            raise ValueError(
                "IRRIWATCH_CLIENT_ID and IRRIWATCH_CLIENT_SECRET must be set in .env "
                "when PROBE_PROVIDER=irriwatch or WEATHER_PROVIDER=irriwatch."
            )
        _irriwatch_instance = IrriWatchAdapter(
            base_url=config.IRRIWATCH_BASE_URL,
            client_id=config.IRRIWATCH_CLIENT_ID,
            client_secret=config.IRRIWATCH_CLIENT_SECRET,
            company_uuid=config.IRRIWATCH_COMPANY_UUID,
        )
    return _irriwatch_instance


def _get_myirrigation(
    config: Settings,
    username: str | None = None,
    password: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    project_id: str | None = None,
    weather_device_id: str | None = None,
):
    """Return a MyIrrigationAdapter, reusing a cached instance for the same credentials.

    Farm-level credentials override global config when provided.
    """
    from app.adapters.myirrigation import MyIrrigationAdapter

    resolved_username = username or config.MYIRRIGATION_USERNAME
    resolved_password = password or config.MYIRRIGATION_PASSWORD
    resolved_client_id = client_id or config.MYIRRIGATION_CLIENT_ID
    resolved_client_secret = client_secret or config.MYIRRIGATION_CLIENT_SECRET
    resolved_project_id = project_id or config.MYIRRIGATION_PROJECT_ID
    resolved_device_id = weather_device_id or config.MYIRRIGATION_WEATHER_DEVICE_ID

    if not resolved_username or not resolved_password:
        raise ValueError(
            "MyIrrigation credentials not configured. Set MYIRRIGATION_USERNAME and "
            "MYIRRIGATION_PASSWORD in .env or via FarmCredentials for the farm."
        )

    cache_key = (
        config.MYIRRIGATION_BASE_URL,
        resolved_username,
        resolved_client_id,
        resolved_project_id,
        resolved_device_id,
    )
    if cache_key not in _myirrigation_cache:
        _myirrigation_cache[cache_key] = MyIrrigationAdapter(
            base_url=config.MYIRRIGATION_BASE_URL,
            username=resolved_username,
            password=resolved_password,
            client_id=resolved_client_id,
            client_secret=resolved_client_secret,
            project_id=resolved_project_id,
            weather_device_id=resolved_device_id,
        )
    return _myirrigation_cache[cache_key]


def get_probe_provider(config: Settings, farm=None) -> ProbeDataProvider:
    """Return a probe provider for the given farm (or global config if farm is None).

    farm.credentials must be eagerly loaded before calling this function.
    """
    match config.PROBE_PROVIDER:
        case "mock":
            return MockProbeProvider()
        case "irriwatch":
            return _get_irriwatch(config)
        case "myirrigation":
            creds = farm.credentials if farm is not None else None
            return _get_myirrigation(
                config,
                username=creds.username if creds else None,
                password=creds.password if creds else None,
                client_id=creds.client_id if creds else None,
                client_secret=creds.client_secret if creds else None,
            )
        case _:
            raise ValueError(
                f"Unknown probe provider: '{config.PROBE_PROVIDER}'. "
                f"Valid options: mock, irriwatch, myirrigation."
            )


def get_weather_provider(config: Settings, farm=None) -> WeatherDataProvider:
    """Return a weather provider for the given farm (or global config if farm is None).

    farm.credentials must be eagerly loaded before calling this function.
    """
    match config.WEATHER_PROVIDER:
        case "mock":
            return MockWeatherProvider(latitude=38.57)
        case "irriwatch":
            return _get_irriwatch(config)
        case "myirrigation":
            creds = farm.credentials if farm is not None else None
            return _get_myirrigation(
                config,
                username=creds.username if creds else None,
                password=creds.password if creds else None,
                client_id=creds.client_id if creds else None,
                client_secret=creds.client_secret if creds else None,
                weather_device_id=creds.weather_device_id if creds else None,
            )
        case _:
            raise ValueError(
                f"Unknown weather provider: '{config.WEATHER_PROVIDER}'. "
                f"Valid options: mock, irriwatch, myirrigation."
            )
