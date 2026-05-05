"""MyIrrigation API adapter — ESPORÃO OLIVAL.

Implements both ProbeDataProvider and WeatherDataProvider using the
MyIrrigation REST API (api.myirrigation.eu).

Authentication:
    POST /api/v1/login with form-encoded fields:
        username, password, client_id, client_secret
    Returns {"token": "<jwt>", ...} with status 201.

Key endpoints consumed:
    POST  /api/v1/login                                         → JWT token (201)
    GET   /api/v1/data/projects                                 → list projects
    GET   /api/v1/data/devices                                  → list devices
    POST  /api/v1/data/devices/{id}/data?use_key_index=         → device data (columnar)
    GET   /api/v1/data/projects/{id}/weather_forecast/detailed  → weather forecast (JSON)

Device data response format (columnar):
    {
      "success": true,
      "data": {
        "sensors": [{"id": "17_0_0", "sensor_type": "Suction", "name": "WM 40cm", "units": "cBar"}, ...],
        "datetimes": [unix_ms_int, ...],
        "values": {"17_0_0": {"unix_ms_str": value, ...}, ...}
      }
    }

Probe external_id convention: "{project_id}/{device_id}"  e.g. "1044/4664"

ESPORÃO OLIVAL (project 1044) devices:
    Soil probes (Watermark suction, cBar at 40cm + 60cm):
        4661 WM03, 4662 WM02, 4663 WM01, 4664 WM06 (T4 OLIVAL),
        4665 WM07 (T17), 4666 WM04, 4667 WM05
    Weather station (hourly, includes daily ET0):
        1583 iMetos Esporão

.env settings:
    PROBE_PROVIDER=myirrigation
    WEATHER_PROVIDER=myirrigation
    MYIRRIGATION_BASE_URL=https://api.myirrigation.eu/api/v1
    MYIRRIGATION_USERNAME=esporao_api
    MYIRRIGATION_PASSWORD=esporao_api
    MYIRRIGATION_CLIENT_ID=7JTTP4XGVZ9S1M7PEABD
    MYIRRIGATION_CLIENT_SECRET=PKVSK5BPNNYE4JE2KOQ2
    MYIRRIGATION_PROJECT_ID=1044
    MYIRRIGATION_WEATHER_DEVICE_ID=1583
"""

import asyncio
import logging
import random
import re
from collections import defaultdict
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

# Sensor types we ingest as soil moisture readings
_SOIL_SENSOR_TYPES = {"suction", "soil moisture", "vwc", "watermark"}

# Re-auth margin before expiry
_TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

# Default token lifetime when not returned by API
_DEFAULT_TOKEN_TTL_SECONDS = 86400  # 24 h

# Date format for POST form fields
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# Retry policy for transient HTTP / network errors
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds; doubles each attempt
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


async def _with_backoff(coro_factory, label: str):
    """Run coro_factory() with exponential back-off on transient errors.

    Retries on HTTP 5xx / 429 and network-level failures. Does NOT retry
    on 4xx client errors (those indicate a logic / auth issue, not flakiness).
    Jitter is applied so parallel workers do not storm the API together.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return await coro_factory()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRY_STATUSES:
                raise
            last_exc = exc
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            last_exc = exc

        if attempt < _MAX_RETRIES - 1:
            wait = _RETRY_BACKOFF_BASE * (2 ** attempt) * (0.5 + random.random() * 0.5)
            logger.warning(
                "MyIrrigation: %s transient error (attempt %d/%d), retrying in %.1fs — %s",
                label, attempt + 1, _MAX_RETRIES, wait, last_exc,
            )
            await asyncio.sleep(wait)

    raise last_exc  # type: ignore[misc]


class MyIrrigationAdapter(ProbeDataProvider, WeatherDataProvider):
    """Adapter for MyIrrigation REST API.

    A singleton instance is shared for probe + weather calls (via factory) so
    the JWT token is reused across both. All credentials come from Settings
    at construction time — never hardcoded.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        client_id: str,
        client_secret: str,
        project_id: str = "",
        weather_device_id: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client_id = client_id
        self._client_secret = client_secret
        self._project_id = project_id
        self._weather_device_id = weather_device_id

        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public domain helpers
    # ------------------------------------------------------------------

    async def get_projects(self) -> list[dict]:
        """GET /data/projects — list all irrigation projects."""
        result = await self._get_json("/data/projects")
        return result if isinstance(result, list) else []

    async def get_devices(self) -> list[dict]:
        """GET /data/devices — list all sensor devices."""
        result = await self._get_json("/data/devices")
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> None:
        """Obtain or reuse a JWT via POST /login (form-encoded body).

        The API returns 201 on success with {"token": "..."}.
        Token cached in-process and refreshed before expiry.
        """
        if self._is_token_valid():
            return

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/login",
                data={
                    "username": self._username,
                    "password": self._password,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        token = data.get("token") or data.get("access_token")
        if not token:
            raise RuntimeError(
                f"MyIrrigation /login did not return a token. "
                f"Response keys: {list(data.keys())}"
            )

        expires_in = int(
            data.get("expires_in")
            or data.get("token_expires_in")
            or _DEFAULT_TOKEN_TTL_SECONDS
        )
        self._token = token
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        logger.info("MyIrrigation authenticated — token valid for %ds", expires_in)

    def _is_token_valid(self) -> bool:
        if not self._token or not self._token_expires_at:
            return False
        return datetime.now(UTC) < self._token_expires_at - _TOKEN_REFRESH_MARGIN

    def _auth_headers(self) -> dict:
        if not self._token:
            raise RuntimeError(
                "MyIrrigationAdapter: not authenticated — call authenticate() first"
            )
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Core HTTP helpers (GET and POST-form) with 401/403 re-auth + retry
    # ------------------------------------------------------------------

    async def _get_json(self, path: str, params: dict | None = None) -> list | dict:
        """GET with auth, re-auth on 401/403, backoff on 5xx / network errors."""
        await self.authenticate()

        async def _do():
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers=self._auth_headers(),
                )
                if resp.status_code in (401, 403):
                    logger.warning("MyIrrigation: %s on GET %s — re-authenticating", resp.status_code, path)
                    self._token = None
                    self._token_expires_at = None
                    await self.authenticate()
                    resp = await client.get(
                        f"{self._base_url}{path}",
                        params=params,
                        headers=self._auth_headers(),
                    )
                resp.raise_for_status()
                return resp.json()

        return await _with_backoff(_do, f"GET {path}")

    async def _post_form_json(
        self,
        path: str,
        form_data: dict,
        params: dict | None = None,
    ) -> list | dict:
        """POST with form-encoded body and auth, re-auth on 401/403, backoff on 5xx / network errors."""
        await self.authenticate()

        async def _do():
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._base_url}{path}",
                    data=form_data,
                    params=params,
                    headers=self._auth_headers(),
                )
                if resp.status_code in (401, 403):
                    logger.warning("MyIrrigation: %s on POST %s — re-authenticating", resp.status_code, path)
                    self._token = None
                    self._token_expires_at = None
                    await self.authenticate()
                    resp = await client.post(
                        f"{self._base_url}{path}",
                        data=form_data,
                        params=params,
                        headers=self._auth_headers(),
                    )
                resp.raise_for_status()
                return resp.json()

        return await _with_backoff(_do, f"POST {path}")

    # ------------------------------------------------------------------
    # ProbeDataProvider
    # ------------------------------------------------------------------

    async def fetch_readings(
        self,
        probe_external_id: str,
        since: datetime,
        until: datetime,
    ) -> list[ProbeReadingDTO]:
        """Fetch soil suction readings for a WM probe over a date range.

        Uses POST /data/devices/{device_id}/data with form fields:
            start_date: "YYYY-MM-DD HH:MM:SS"
            end_date:   "YYYY-MM-DD HH:MM:SS"

        The API returns columnar JSON with unix-ms timestamps.
        Returns [] on any error (safe for scheduler loops).
        """
        _project_id, device_id = _parse_external_id(probe_external_id)

        try:
            raw = await self._post_form_json(
                f"/data/devices/{device_id}/data",
                form_data={
                    "start_date": since.strftime(_DATE_FMT),
                    "end_date": until.strftime(_DATE_FMT),
                },
                params={"use_key_index": ""},
            )
        except Exception:
            logger.exception("MyIrrigation: failed to fetch data for device %s", device_id)
            return []

        readings = _parse_device_readings(raw, probe_external_id)
        logger.debug(
            "MyIrrigation device %s: %d readings from %s to %s",
            device_id, len(readings),
            since.strftime(_DATE_FMT), until.strftime(_DATE_FMT),
        )
        return readings

    async def fetch_probe_metadata(self, probe_external_id: str) -> ProbeMetadataDTO:
        _project_id, device_id = _parse_external_id(probe_external_id)
        try:
            devices = await self.get_devices()
            for dev in devices:
                if str(dev.get("id", "")) == str(device_id):
                    return _device_to_metadata(dev, probe_external_id)
        except Exception:
            logger.exception("MyIrrigation: failed to fetch metadata for device %s", device_id)

        return ProbeMetadataDTO(
            external_id=probe_external_id,
            manufacturer="MyIrrigation",
            model="Watermark WM200SS",
            depths_cm=[40, 60],
            status="unknown",
        )

    async def list_probes(self) -> list[ProbeMetadataDTO]:
        """Return all devices as ProbeMetadataDTOs."""
        try:
            projects = await self.get_projects()
            devices = await self.get_devices()
        except Exception:
            logger.exception("MyIrrigation: failed to list probes")
            return []

        project_map: dict[str, dict] = {str(p.get("id", "")): p for p in projects}
        probes: list[ProbeMetadataDTO] = []

        for dev in devices:
            device_id = str(dev.get("id", ""))
            project_id = str(dev.get("project_id", ""))
            external_id = f"{project_id}/{device_id}"
            probes.append(_device_to_metadata(dev, external_id))

            if project_id and project_id not in project_map:
                logger.debug("Device %s references unknown project %s", device_id, project_id)

        return probes

    async def health_check(self) -> bool:
        try:
            await self.authenticate()
            projects = await self.get_projects()
            return isinstance(projects, list)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # WeatherDataProvider
    # ------------------------------------------------------------------

    async def _get_weather_project_id(self) -> str:
        if self._project_id:
            return self._project_id
        projects = await self.get_projects()
        if not projects:
            raise RuntimeError("MyIrrigation: no projects found for weather endpoint")
        pid = str(projects[0].get("id", ""))
        if not pid:
            raise RuntimeError("MyIrrigation: first project has no 'id' field")
        self._project_id = pid
        logger.info("MyIrrigation: auto-detected weather project_id=%s", pid)
        return pid

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 5,
    ) -> list[WeatherForecastDTO]:
        """Fetch weather forecast from /data/projects/{id}/weather_forecast/detailed."""
        try:
            project_id = await self._get_weather_project_id()
            raw = await self._get_json(
                f"/data/projects/{project_id}/weather_forecast/detailed"
            )
        except Exception:
            logger.exception("MyIrrigation: fetch_forecast failed")
            return []

        return _parse_forecast_response(raw, days)

    async def fetch_observations(
        self,
        lat: float,
        lon: float,
        since: datetime,
        until: datetime,
    ) -> list[WeatherObservationDTO]:
        """Fetch historical weather from the iMetos station (weather device).

        Fetches hourly data from the configured weather device and aggregates
        to daily observations.
        """
        if not self._weather_device_id:
            logger.warning("MyIrrigation: MYIRRIGATION_WEATHER_DEVICE_ID not set — no observations")
            return []

        try:
            raw = await self._post_form_json(
                f"/data/devices/{self._weather_device_id}/data",
                form_data={
                    "start_date": since.strftime(_DATE_FMT),
                    "end_date": until.strftime(_DATE_FMT),
                },
                params={"use_key_index": ""},
            )
        except Exception:
            logger.exception("MyIrrigation: fetch_observations failed")
            return []

        return _parse_weather_observations(raw, since, until)

    async def fetch_et0(
        self,
        lat: float,
        lon: float,
        for_date: date,
    ) -> float | None:
        """Fetch pre-computed ET0 from the iMetos station for a specific date."""
        if not self._weather_device_id:
            return None

        day_start = datetime(for_date.year, for_date.month, for_date.day, 0, 0, 0, tzinfo=UTC)
        day_end = datetime(for_date.year, for_date.month, for_date.day, 23, 59, 59, tzinfo=UTC)

        try:
            raw = await self._post_form_json(
                f"/data/devices/{self._weather_device_id}/data",
                form_data={
                    "start_date": day_start.strftime(_DATE_FMT),
                    "end_date": day_end.strftime(_DATE_FMT),
                },
                params={"use_key_index": ""},
            )
        except Exception:
            logger.exception("MyIrrigation: fetch_et0 failed")
            return None

        return _extract_et0_from_device_data(raw, for_date)


# ---------------------------------------------------------------------------
# Device data parser — columnar format
# ---------------------------------------------------------------------------

def _parse_device_readings(raw: dict | list, probe_external_id: str) -> list[ProbeReadingDTO]:
    """Parse the MyIrrigation columnar device data response into ProbeReadingDTOs.

    Response shape:
        {"success": true, "data": {"sensors": [...], "datetimes": [...], "values": {...}}}

    Only "Suction" (cBar) sensors at known depths are extracted.
    Negative values (e.g. -252) are stored as-is and flagged invalid by ingestion.
    """
    if isinstance(raw, dict) and "data" in raw:
        data = raw["data"]
    elif isinstance(raw, dict):
        data = raw
    else:
        return []

    if not isinstance(data, dict):
        return []

    sensors: list[dict] = data.get("sensors") or []
    values_map: dict[str, dict] = data.get("values") or {}

    # Index soil sensors by their API id
    soil_sensors = [
        s for s in sensors
        if s.get("sensor_type", "").lower() in _SOIL_SENSOR_TYPES
    ]
    if not soil_sensors:
        logger.debug("MyIrrigation %s: no soil sensors in response", probe_external_id)
        return []

    readings: list[ProbeReadingDTO] = []

    for sensor in soil_sensors:
        sensor_id = sensor.get("id", "")
        depth_cm = _depth_from_sensor_name(sensor.get("name", ""))
        units = sensor.get("units", "").lower()
        unit_key = _normalise_unit(units)

        sensor_values = values_map.get(sensor_id)
        if not isinstance(sensor_values, dict):
            continue

        for ts_str, raw_val in sensor_values.items():
            if raw_val is None:
                continue
            try:
                value = float(raw_val)
            except (TypeError, ValueError):
                continue

            # iMetos "no data" sentinels for Watermark (cBar) sensors
            if unit_key == "soil_tension_cbar" and (value <= -200 or value >= 253):
                continue

            # Normalise VWC: iMetos TDT probes report vol% (e.g. 23.3).
            # Our internal unit is m³/m³ (fractional). Any value > 1.0 is
            # unambiguously in percentage scale → divide by 100.
            if unit_key == "vwc_m3m3" and value > 1.0:
                value = value / 100.0
            raw_value = value

            ts = _unix_ms_to_datetime(ts_str)
            if ts is None:
                continue

            readings.append(
                ProbeReadingDTO(
                    probe_external_id=probe_external_id,
                    depth_cm=depth_cm,
                    timestamp=ts,
                    raw_value=raw_value,
                    calibrated_value=value,
                    unit=unit_key,
                    sensor_type="moisture",
                )
            )

    return sorted(readings, key=lambda r: (r.depth_cm, r.timestamp))


def _parse_weather_observations(
    raw: dict | list,
    since: datetime,
    until: datetime,
) -> list[WeatherObservationDTO]:
    """Parse iMetos hourly device data into daily WeatherObservationDTOs.

    Groups hourly readings by calendar date, computes max/min/mean temperature,
    total rainfall, mean wind, and carries the daily ET0 value.
    """
    if isinstance(raw, dict) and "data" in raw:
        data = raw["data"]
    else:
        data = raw if isinstance(raw, dict) else {}

    sensors: list[dict] = data.get("sensors") or []
    values_map: dict[str, dict] = data.get("values") or {}

    # Map sensor_type → sensor_id (take first non-None match)
    def first_sensor(type_pattern: str) -> str | None:
        for s in sensors:
            if type_pattern.lower() in s.get("sensor_type", "").lower():
                sid = s.get("id", "")
                if isinstance(values_map.get(sid), dict):
                    return sid
        return None

    temp_sid = first_sensor("air temperature")
    rain_sid = first_sensor("precipitation")
    solar_sid = first_sensor("solar radiation")
    rh_sid = first_sensor("relative humidity")
    wind_sid = first_sensor("wind speed")
    et0_sid = first_sensor("et0")

    # Detect solar radiation units — iMetos reports in W/m² (irradiance).
    # Penman-Monteith needs MJ/m²/day so we convert: mean W/m² × 0.0864 = MJ/m²/day.
    solar_units = ""
    if solar_sid:
        for s in sensors:
            if s.get("id") == solar_sid:
                solar_units = s.get("units", "").lower().strip()
                break
    _solar_is_wm2 = solar_units in ("w/m2", "w/m²", "wm2", "wm²", "") or "w" in solar_units

    # Build daily buckets
    daily: dict[date, dict] = defaultdict(lambda: {
        "temps": [], "rain": 0.0, "solar": [], "rh": [], "wind": [], "et0": None
    })

    def add_values(sid: str | None, key: str, agg: str = "list"):
        if sid is None:
            return
        vmap = values_map.get(sid)
        if not isinstance(vmap, dict):
            return
        for ts_str, val in vmap.items():
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            ts = _unix_ms_to_datetime(ts_str)
            if ts is None or ts < since or ts > until:
                continue
            d = ts.date()
            if agg == "list":
                daily[d][key].append(fval)
            elif agg == "sum":
                daily[d][key] += fval
            elif agg == "et0":
                daily[d]["et0"] = fval  # last one wins (daily value)

    add_values(temp_sid, "temps", "list")
    add_values(rain_sid, "rain", "sum")
    add_values(solar_sid, "solar", "list")
    add_values(rh_sid, "rh", "list")
    add_values(wind_sid, "wind", "list")
    add_values(et0_sid, "et0", "et0")

    observations: list[WeatherObservationDTO] = []
    for day, bucket in sorted(daily.items()):
        ts = datetime(day.year, day.month, day.day, 12, 0, 0, tzinfo=UTC)
        temps = bucket["temps"]
        solars = bucket["solar"]
        rhs = bucket["rh"]
        winds = bucket["wind"]

        solar_mean = sum(solars) / len(solars) if solars else None
        if solar_mean is not None and _solar_is_wm2:
            # iMetos reports instantaneous W/m²; convert mean to daily MJ/m²/day
            solar_mean = solar_mean * 0.0864

        obs = WeatherObservationDTO(
            timestamp=ts,
            temperature_max_c=max(temps) if temps else None,
            temperature_min_c=min(temps) if temps else None,
            temperature_mean_c=sum(temps) / len(temps) if temps else None,
            humidity_pct=sum(rhs) / len(rhs) if rhs else None,
            wind_speed_ms=sum(winds) / len(winds) if winds else None,
            solar_radiation_mjm2=solar_mean,
            rainfall_mm=bucket["rain"] or 0.0,
            et0_mm=bucket["et0"],
        )
        observations.append(obs)

    return observations


def _extract_et0_from_device_data(raw: dict | list, for_date: date) -> float | None:
    """Extract the daily ET0 value for a specific date from device data."""
    if isinstance(raw, dict) and "data" in raw:
        data = raw["data"]
    else:
        return None

    sensors: list[dict] = data.get("sensors") or []
    values_map: dict[str, dict] = data.get("values") or {}

    for s in sensors:
        if "et0" in s.get("sensor_type", "").lower():
            sid = s.get("id", "")
            vmap = values_map.get(sid)
            if not isinstance(vmap, dict):
                continue
            for ts_str, val in vmap.items():
                ts = _unix_ms_to_datetime(ts_str)
                if ts and ts.date() == for_date and val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
    return None


# ---------------------------------------------------------------------------
# Weather forecast parser
# ---------------------------------------------------------------------------

def _parse_forecast_response(raw: list | dict, days: int) -> list[WeatherForecastDTO]:
    """Parse /weather_forecast/detailed JSON into WeatherForecastDTOs.

    Actual response shape:
        {
          "metadata": {...},
          "units": {...},
          "defs": [...],
          "values": {
            "2026-04-14": {
              "date": "2026-04-14",
              "temperature_max": 19.74,
              "temperature_min": 7.77,
              "temperature_mean": 14.03,
              "precipitation": 0,
              "precipitation_probability": 0,
              "windspeed_mean": 1.07,
              "relativehumidity_max": 100,
              "relativehumidity_min": 53,
              "referenceevapotranspiration_fao": 2.9,
              ...
            },
            "2026-04-15": {...},
            ...
          }
        }
    """
    issued_at = datetime.now(UTC)
    today = datetime.now(UTC).date()

    if not isinstance(raw, dict):
        return []

    values = raw.get("values", {})
    if not isinstance(values, dict):
        return []

    forecasts: list[WeatherForecastDTO] = []
    for date_str in sorted(values.keys()):
        if len(forecasts) >= days:
            break
        entry = values[date_str]
        if not isinstance(entry, dict):
            continue
        try:
            fc_date = date.fromisoformat(date_str)
        except ValueError:
            continue
        if fc_date < today:
            continue

        rh_max = _get_float(entry, "relativehumidity_max")
        rh_min = _get_float(entry, "relativehumidity_min")
        rh_mean = (
            (rh_max + rh_min) / 2
            if rh_max is not None and rh_min is not None
            else (rh_max or rh_min)
        )

        forecasts.append(WeatherForecastDTO(
            forecast_date=fc_date,
            issued_at=issued_at,
            temperature_max_c=_get_float(entry, "temperature_max"),
            temperature_min_c=_get_float(entry, "temperature_min"),
            humidity_pct=rh_mean,
            wind_speed_ms=_get_float(entry, "windspeed_mean"),
            rainfall_mm=_get_float(entry, "precipitation"),
            rainfall_probability_pct=_get_float(entry, "precipitation_probability"),
            et0_mm=_get_float(entry, "referenceevapotranspiration_fao"),
        ))

    return forecasts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_external_id(external_id: str) -> tuple[str, str]:
    """Parse "{project_id}/{device_id}" → (project_id, device_id)."""
    parts = external_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid MyIrrigation probe external_id '{external_id}'. "
            "Expected format: '{{project_id}}/{{device_id}}'"
        )
    return parts[0], parts[1]


def _device_to_metadata(dev: dict, external_id: str) -> ProbeMetadataDTO:
    return ProbeMetadataDTO(
        external_id=external_id,
        serial_number=str(dev.get("serial") or dev.get("serial_number") or ""),
        manufacturer="MyIrrigation",
        model=str(dev.get("model") or dev.get("type") or "Watermark WM200SS"),
        depths_cm=[40, 60],
        status=str(dev.get("status") or "ok"),
    )


def _depth_from_sensor_name(name: str) -> int:
    """Extract depth in cm from a sensor name like 'WM 40cm' or 'Soil 60cm'.

    Falls back to 40 if no depth pattern found.
    """
    m = re.search(r"(\d+)\s*cm", name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 40  # default to shallowest depth


def _normalise_unit(units_str: str) -> str:
    """Map raw unit strings to our internal unit keys."""
    u = units_str.lower().strip()
    if u in ("cbar", "cb", "kpa"):
        return "soil_tension_cbar"
    if u in ("m3/m3", "m³/m³", "vwc", "vol %", "vol%", "%"):
        return "vwc_m3m3"
    return u or "soil_tension_cbar"


def _unix_ms_to_datetime(ts_ms: int | str | float) -> datetime | None:
    """Convert a unix-millisecond timestamp (int or string) to UTC datetime."""
    try:
        ms = int(ts_ms)
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _date_from_entry(entry: dict) -> date | None:
    for key in ("date", "forecast_date", "day", "datetime", "timestamp"):
        raw = entry.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and raw > 1e9:
            return _unix_ms_to_datetime(raw)
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                pass
    return None


def _get_float(data: dict, *keys: str) -> float | None:
    for key in keys:
        val = data.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None
