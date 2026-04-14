"""Abstract base classes for all data providers.

To add a new vendor:
1. Create a new class implementing ProbeDataProvider or WeatherDataProvider
2. Map the vendor's response to the standard DTOs in dto.py
3. Register the provider name in adapters/factory.py
4. Set PROBE_PROVIDER=<name> or WEATHER_PROVIDER=<name> in .env

No other code needs to change.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime

from app.adapters.dto import (
    ProbeMetadataDTO,
    ProbeReadingDTO,
    WeatherForecastDTO,
    WeatherObservationDTO,
)


class ProbeDataProvider(ABC):
    """Interface for fetching probe/sensor data from any vendor.

    Implementers:
    - MockProbeProvider (built-in, for dev/testing)
    - Future: [VendorName]Provider when real API is provided
    """

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the provider (obtain token, verify API key, etc.).
        Called once before any data fetch. Implementations may cache the token.
        """

    @abstractmethod
    async def fetch_readings(
        self,
        probe_external_id: str,
        since: datetime,
        until: datetime,
    ) -> list[ProbeReadingDTO]:
        """Fetch readings for a single probe over a time range.

        Args:
            probe_external_id: The provider's identifier for the probe.
            since: Start of range (inclusive, tz-aware).
            until: End of range (inclusive, tz-aware).

        Returns:
            List of normalized ProbeReadingDTO, one per (depth, timestamp) pair.
        """

    @abstractmethod
    async def fetch_probe_metadata(self, probe_external_id: str) -> ProbeMetadataDTO:
        """Fetch static metadata for a single probe (model, depths, status)."""

    @abstractmethod
    async def list_probes(self) -> list[ProbeMetadataDTO]:
        """List all probes available on this provider account."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and responding."""


class WeatherDataProvider(ABC):
    """Interface for fetching weather observations and forecasts.

    Implementers:
    - MockWeatherProvider (built-in, for dev/testing)
    - Future: [VendorName]Provider when real API is provided
    """

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the provider."""

    @abstractmethod
    async def fetch_observations(
        self,
        lat: float,
        lon: float,
        since: datetime,
        until: datetime,
    ) -> list[WeatherObservationDTO]:
        """Fetch historical weather observations for a location and time range."""

    @abstractmethod
    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 5,
    ) -> list[WeatherForecastDTO]:
        """Fetch N-day forecast for a location."""

    @abstractmethod
    async def fetch_et0(
        self,
        lat: float,
        lon: float,
        for_date: date,
    ) -> float | None:
        """Fetch pre-computed ET0 for a location and date, or None if unavailable.

        When None is returned, the engine falls back to its own ET0 computation.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and responding."""
