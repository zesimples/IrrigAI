"""Adapter factory.

Maps provider names (from .env) to concrete implementations.
To add a new vendor: create a class implementing ProbeDataProvider or
WeatherDataProvider, import it here, and add a branch.
"""

from app.adapters.base import ProbeDataProvider, WeatherDataProvider
from app.adapters.mock_probe import MockProbeProvider
from app.adapters.mock_weather import MockWeatherProvider
from app.config import Settings

# Adapters are lazily imported to avoid hard dependency on httpx at startup
_irriwatch_instance: "IrriWatchAdapter | None" = None  # type: ignore[name-defined]
_myirrigation_instance: "MyIrrigationAdapter | None" = None  # type: ignore[name-defined]


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


def _get_myirrigation(config: Settings):
    """Return a singleton MyIrrigationAdapter (shared for probe + weather)."""
    global _myirrigation_instance
    if _myirrigation_instance is None:
        from app.adapters.myirrigation import MyIrrigationAdapter
        if not config.MYIRRIGATION_USERNAME or not config.MYIRRIGATION_PASSWORD:
            raise ValueError(
                "MYIRRIGATION_USERNAME and MYIRRIGATION_PASSWORD must be set in .env "
                "when PROBE_PROVIDER=myirrigation or WEATHER_PROVIDER=myirrigation."
            )
        _myirrigation_instance = MyIrrigationAdapter(
            base_url=config.MYIRRIGATION_BASE_URL,
            username=config.MYIRRIGATION_USERNAME,
            password=config.MYIRRIGATION_PASSWORD,
            client_id=config.MYIRRIGATION_CLIENT_ID,
            client_secret=config.MYIRRIGATION_CLIENT_SECRET,
            project_id=config.MYIRRIGATION_PROJECT_ID,
            weather_device_id=config.MYIRRIGATION_WEATHER_DEVICE_ID,
        )
    return _myirrigation_instance


def get_probe_provider(config: Settings) -> ProbeDataProvider:
    match config.PROBE_PROVIDER:
        case "mock":
            return MockProbeProvider()
        case "irriwatch":
            return _get_irriwatch(config)
        case "myirrigation":
            return _get_myirrigation(config)
        case _:
            raise ValueError(
                f"Unknown probe provider: '{config.PROBE_PROVIDER}'. "
                f"Valid options: mock, irriwatch, myirrigation."
            )


def get_weather_provider(config: Settings) -> WeatherDataProvider:
    match config.WEATHER_PROVIDER:
        case "mock":
            return MockWeatherProvider(latitude=38.57)
        case "irriwatch":
            return _get_irriwatch(config)
        case "myirrigation":
            return _get_myirrigation(config)
        case _:
            raise ValueError(
                f"Unknown weather provider: '{config.WEATHER_PROVIDER}'. "
                f"Valid options: mock, irriwatch, myirrigation."
            )
