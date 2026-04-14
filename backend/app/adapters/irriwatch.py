"""IrriWatch (Hydrosat B.V.) adapter.

Implements both ProbeDataProvider and WeatherDataProvider using the
IrriWatch satellite-based irrigation advisory API.

Authentication: OAuth2 Client Credentials flow.
Token lifetime: 7 days — cached in-process, refreshed on expiry.

Field-level data endpoint returns daily aggregates per polygon including:
  - soil_moisture_root_zone (m³/m³)   → VWC probe reading at depth 30cm
  - penmann_monteith_reference_et0    → ET0 (mm/day)
  - air_temperature_24 / _min_24      → mean/min air temp
  - relative_humidity_24              → humidity %
  - precipitation_fcdp0..7            → 8-day rainfall forecast (mm/day)
  - et_fcdp0..7                       → 8-day ET0 forecast (mm/day)

Probe external_id convention (how probes are stored in our DB):
    "{order_uuid}/{field_name}"
The adapter parses this to know which IrriWatch order and field to query.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import httpx

from app.adapters.base import ProbeDataProvider, WeatherDataProvider
from app.adapters.dto import (
    ProbeMetadataDTO,
    ProbeReadingDTO,
    WeatherForecastDTO,
    WeatherObservationDTO,
)

logger = logging.getLogger(__name__)

_TOKEN_ENDPOINT_CANDIDATES = [
    "/oauth/v2/token",
    "/oauth2/v2/token",
]

# IrriWatch provides daily field-level data — we treat satellite VWC as a
# "virtual probe" at root-zone depth.
_VIRTUAL_PROBE_DEPTH_CM = 30


class IrriWatchAdapter(ProbeDataProvider, WeatherDataProvider):
    """Single adapter that satisfies both ProbeDataProvider and WeatherDataProvider.

    Initialise with your IrriWatch credentials from the .env file.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        company_uuid: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._company_uuid = company_uuid

        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._token_endpoint: str | None = None  # discovered on first auth

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def authenticate(self) -> None:
        """Obtain (or reuse) a Bearer token via OAuth2 client credentials."""
        if self._token and self._token_expires_at:
            # Refresh 5 minutes before expiry
            if datetime.now(UTC) < self._token_expires_at - timedelta(minutes=5):
                return

        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            endpoint = await self._discover_token_endpoint(client, payload)
            resp = await client.post(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()

        self._token = data["access_token"]
        expires_in = int(data.get("expires_in", 604800))  # default 7 days
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        logger.info("IrriWatch authenticated — token valid for %ds", expires_in)

    async def _discover_token_endpoint(
        self, client: httpx.AsyncClient, payload: dict
    ) -> str:
        """Try candidate token endpoints; cache the working one."""
        if self._token_endpoint:
            return self._token_endpoint

        for path in _TOKEN_ENDPOINT_CANDIDATES:
            url = self._base_url + path
            try:
                resp = await client.post(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10,
                )
                if resp.status_code < 400:
                    self._token_endpoint = url
                    return url
            except httpx.RequestError:
                continue

        raise RuntimeError(
            "Could not reach any IrriWatch token endpoint. "
            f"Tried: {[self._base_url + p for p in _TOKEN_ENDPOINT_CANDIDATES]}"
        )

    def _headers(self) -> dict:
        if not self._token:
            raise RuntimeError("Not authenticated — call authenticate() first")
        return {"Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # ProbeDataProvider
    # ------------------------------------------------------------------

    async def fetch_readings(
        self,
        probe_external_id: str,
        since: datetime,
        until: datetime,
    ) -> list[ProbeReadingDTO]:
        """Fetch daily soil moisture readings from IrriWatch field-level data.

        probe_external_id format: "{order_uuid}/{field_name}"
        Returns one ProbeReadingDTO per day with unit="vwc_m3m3".
        """
        order_uuid, field_name = _parse_external_id(probe_external_id)
        readings: list[ProbeReadingDTO] = []

        # IrriWatch provides one result per day; iterate each day in range
        current = since.date()
        end = until.date()

        async with httpx.AsyncClient(timeout=30) as client:
            while current <= end:
                date_str = current.strftime("%Y%m%d")
                data = await self._fetch_field_level(
                    client, order_uuid, date_str
                )
                if data is not None:
                    field_data = _extract_field(data, field_name)
                    if field_data:
                        vwc = _get_float(field_data, "soil_moisture_root_zone")
                        if vwc is not None:
                            ts = datetime(
                                current.year, current.month, current.day,
                                12, 0, 0, tzinfo=UTC  # noon UTC — daily aggregate
                            )
                            readings.append(ProbeReadingDTO(
                                probe_external_id=probe_external_id,
                                depth_cm=_VIRTUAL_PROBE_DEPTH_CM,
                                timestamp=ts,
                                raw_value=vwc,
                                calibrated_value=vwc,
                                unit="vwc_m3m3",
                                sensor_type="moisture",
                            ))
                current += timedelta(days=1)

        logger.debug(
            "IrriWatch probe %s: fetched %d readings from %s to %s",
            probe_external_id, len(readings), since.date(), until.date(),
        )
        return readings

    async def fetch_probe_metadata(self, probe_external_id: str) -> ProbeMetadataDTO:
        order_uuid, field_name = _parse_external_id(probe_external_id)
        return ProbeMetadataDTO(
            external_id=probe_external_id,
            manufacturer="Hydrosat / IrriWatch",
            model="satellite_derived",
            depths_cm=[_VIRTUAL_PROBE_DEPTH_CM],
            status="ok",
        )

    async def list_probes(self) -> list[ProbeMetadataDTO]:
        """List all fields across all orders as virtual probes."""
        await self.authenticate()
        probes: list[ProbeMetadataDTO] = []

        async with httpx.AsyncClient(timeout=30) as client:
            orders = await self._list_orders(client)
            for order in orders:
                order_uuid = order.get("uuid", "")
                geojson = order.get("fields", {})
                features = geojson.get("features", []) if isinstance(geojson, dict) else []
                for feature in features:
                    field_name = (
                        feature.get("properties", {}).get("name")
                        or feature.get("properties", {}).get("id", "")
                    )
                    if field_name:
                        external_id = f"{order_uuid}/{field_name}"
                        probes.append(ProbeMetadataDTO(
                            external_id=external_id,
                            manufacturer="Hydrosat / IrriWatch",
                            model="satellite_derived",
                            depths_cm=[_VIRTUAL_PROBE_DEPTH_CM],
                            status="ok",
                        ))
        return probes

    async def health_check(self) -> bool:
        try:
            await self.authenticate()
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/company",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # WeatherDataProvider
    # ------------------------------------------------------------------

    async def fetch_observations(
        self,
        lat: float,
        lon: float,
        since: datetime,
        until: datetime,
    ) -> list[WeatherObservationDTO]:
        """Extract weather observations from IrriWatch field-level data.

        Uses the first available order and field for this company.
        lat/lon are ignored — IrriWatch data is field-level not point-level.
        """
        order_uuid, field_name = await self._resolve_default_field()
        if not order_uuid:
            logger.warning("IrriWatch: no active order found for weather observations")
            return []

        observations: list[WeatherObservationDTO] = []
        current = since.date()
        end = until.date()

        async with httpx.AsyncClient(timeout=30) as client:
            while current <= end:
                date_str = current.strftime("%Y%m%d")
                data = await self._fetch_field_level(client, order_uuid, date_str)
                if data is not None:
                    field_data = _extract_field(data, field_name)
                    if field_data:
                        obs = _field_to_observation(field_data, current)
                        if obs is not None:
                            observations.append(obs)
                current += timedelta(days=1)

        return observations

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 5,
    ) -> list[WeatherForecastDTO]:
        """Extract multi-day forecast from latest field-level data.

        IrriWatch provides 8-day forecasts (fcdp0..fcdp7) in the latest result.
        """
        order_uuid, field_name = await self._resolve_default_field()
        if not order_uuid:
            return []

        # Get the most recent result
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        date_str = yesterday.strftime("%Y%m%d")

        async with httpx.AsyncClient(timeout=30) as client:
            data = await self._fetch_field_level(client, order_uuid, date_str)

        if data is None:
            return []

        field_data = _extract_field(data, field_name)
        if not field_data:
            return []

        now = datetime.now(UTC)
        forecasts: list[WeatherForecastDTO] = []
        for i in range(min(days, 8)):
            fc_date = datetime.now(UTC).date() + timedelta(days=i + 1)
            rain = _get_float(field_data, f"precipitation_fcdp{i}")
            et0 = _get_float(field_data, f"et_fcdp{i}")
            temp_max = _get_float(field_data, "air_temperature_24")  # approximation
            temp_min = _get_float(field_data, "air_temperature_min_24")
            humidity = _get_float(field_data, "relative_humidity_24")
            forecasts.append(WeatherForecastDTO(
                forecast_date=fc_date,
                issued_at=now,
                temperature_max_c=temp_max,
                temperature_min_c=temp_min,
                humidity_pct=humidity,
                rainfall_mm=rain,
                et0_mm=et0,
            ))

        return forecasts

    async def fetch_et0(self, lat: float, lon: float, for_date: date) -> float | None:
        """Fetch pre-computed ET0 from IrriWatch field-level data."""
        order_uuid, field_name = await self._resolve_default_field()
        if not order_uuid:
            return None

        date_str = for_date.strftime("%Y%m%d")
        async with httpx.AsyncClient(timeout=30) as client:
            data = await self._fetch_field_level(client, order_uuid, date_str)

        if data is None:
            return None
        field_data = _extract_field(data, field_name)
        return _get_float(field_data or {}, "penmann_monteith_reference_et0")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_field_level(
        self,
        client: httpx.AsyncClient,
        order_uuid: str,
        date_str: str,
    ) -> list | dict | None:
        """GET field-level JSON for a specific date. Returns None on error."""
        url = (
            f"{self._base_url}/api/v1/company/{self._company_uuid}"
            f"/order/{order_uuid}/result/{date_str}/field_level"
        )
        try:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 404:
                logger.debug("IrriWatch: no data for %s on %s", order_uuid, date_str)
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("IrriWatch field_level HTTP %s for %s/%s", exc.response.status_code, order_uuid, date_str)
            return None
        except Exception:
            logger.exception("IrriWatch field_level fetch failed for %s/%s", order_uuid, date_str)
            return None

    async def _list_orders(self, client: httpx.AsyncClient) -> list[dict]:
        url = f"{self._base_url}/api/v1/company/{self._company_uuid}/order"
        try:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception("IrriWatch: failed to list orders")
            return []

    async def _resolve_default_field(self) -> tuple[str, str]:
        """Return (order_uuid, field_name) for the first active order+field.

        Used for weather lookups where a specific field isn't specified.
        Result is cached after first successful resolution.
        """
        if hasattr(self, "_cached_default_field"):
            return self._cached_default_field

        await self.authenticate()
        async with httpx.AsyncClient(timeout=30) as client:
            orders = await self._list_orders(client)

        for order in orders:
            if order.get("state") in ("canceled", "ended"):
                continue
            order_uuid = order.get("uuid", "")
            geojson = order.get("fields", {})
            features = geojson.get("features", []) if isinstance(geojson, dict) else []
            if features:
                field_name = (
                    features[0].get("properties", {}).get("name")
                    or features[0].get("properties", {}).get("id", "")
                )
                if order_uuid and field_name:
                    self._cached_default_field = (order_uuid, field_name)
                    return self._cached_default_field

        self._cached_default_field = ("", "")
        return ("", "")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_external_id(external_id: str) -> tuple[str, str]:
    """Parse "{order_uuid}/{field_name}" → (order_uuid, field_name)."""
    parts = external_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid IrriWatch probe external_id '{external_id}'. "
            "Expected format: '{{order_uuid}}/{{field_name}}'"
        )
    return parts[0], parts[1]


def _extract_field(data: list | dict, field_name: str) -> dict | None:
    """Extract a specific field's data from IrriWatch's field-level response.

    Handles two response formats observed in the API:
    1. List of dicts: [{"name": "field_name", "soil_moisture_root_zone": 0.25, ...}]
    2. Dict keyed by field name: {"field_name": {"soil_moisture_root_zone": 0.25, ...}}
    """
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("field_name") or entry.get("id", "")
                if name == field_name:
                    return entry
        # Fallback: return first entry if no name match (single-field orders)
        if data and isinstance(data[0], dict):
            return data[0]
    elif isinstance(data, dict):
        if field_name in data:
            return data[field_name]
        # Single-field response keyed differently
        if len(data) == 1:
            return next(iter(data.values()))
    return None


def _get_float(data: dict, key: str) -> float | None:
    val = data.get(key)
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _field_to_observation(field_data: dict, day: date) -> WeatherObservationDTO | None:
    """Convert IrriWatch field-level data dict to a WeatherObservationDTO."""
    et0 = _get_float(field_data, "penmann_monteith_reference_et0")
    temp_mean = _get_float(field_data, "air_temperature_24")
    temp_min = _get_float(field_data, "air_temperature_min_24")
    humidity = _get_float(field_data, "relative_humidity_24")

    # At least ET0 or temperature must be present
    if et0 is None and temp_mean is None:
        return None

    ts = datetime(day.year, day.month, day.day, 12, 0, 0, tzinfo=UTC)
    return WeatherObservationDTO(
        timestamp=ts,
        temperature_max_c=None,  # IrriWatch only provides mean and min
        temperature_min_c=temp_min,
        temperature_mean_c=temp_mean,
        humidity_pct=humidity,
        wind_speed_ms=None,
        solar_radiation_mjm2=None,
        rainfall_mm=None,
        et0_mm=et0,
    )
