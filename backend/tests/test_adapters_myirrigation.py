"""Tests for the MyIrrigation adapter.

Covers:
- Successful login and token caching
- Project and device list fetching
- Probe reading extraction and DTO mapping
- 401/403 re-authentication retry flow
- Factory wiring for probe + weather providers
- Parsing helpers (external_id, timestamp, float extraction)
"""

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.adapters.myirrigation import (
    MyIrrigationAdapter,
    _depth_from_sensor_name,
    _get_float,
    _normalise_unit,
    _parse_device_readings,
    _parse_external_id,
    _unix_ms_to_datetime,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "http://api.myirrigation.eu/api/v1"
USERNAME = "test_user"
PASSWORD = "test_pass"
CLIENT_ID = "TEST_CLIENT_ID"
CLIENT_SECRET = "TEST_CLIENT_SECRET"

FAKE_TOKEN = "eyJ.fake.jwt"
TOKEN_RESPONSE = {"token": FAKE_TOKEN, "expires_in": 3600}

PROJECTS = [
    {"id": "1044", "name": "ESPORÃO OLIVAL"},
    {"id": "604", "name": "ESPORÃO VINHA"},
]

DEVICES = [
    {"id": "4664", "name": "WM06 - T4 WM OLIVAL NBIOT", "serial": "WM06", "status": "ok"},
    {"id": "4665", "name": "WM07 - T17 WM NBIOT", "serial": "WM07", "status": "ok"},
    {"id": "1583", "name": "iMetos Esporão", "serial": "PESSL_1583", "status": "ok"},
]

# Real API columnar response for a WM Watermark device
# values dict keys are unix-ms as strings
DEVICE_DATA_RESPONSE = {
    "success": True,
    "data": {
        "sensors": [
            {"id": "17_0_0", "source_name": "Sensor", "sensor_type": "Suction",
             "name": "WM 40cm", "units": "cBar"},
            {"id": "18_1_0", "source_name": "Sensor", "sensor_type": "Suction",
             "name": "WM 60cm", "units": "cBar"},
            {"id": "1_2_0", "source_name": "Sensor", "sensor_type": "Battery",
             "name": "Battery", "units": "mV"},
        ],
        "datetimes": [1717243200000, 1717246800000],
        "values": {
            "17_0_0": {"1717243200000": 45, "1717246800000": 48},
            "18_1_0": {"1717243200000": 32, "1717246800000": 35},
            "1_2_0": {"1717243200000": 6500, "1717246800000": 6480},
        },
    },
}


def make_adapter() -> MyIrrigationAdapter:
    return MyIrrigationAdapter(
        base_url=BASE_URL,
        username=USERNAME,
        password=PASSWORD,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        project_id="1044",
        weather_device_id="1583",
    )


def mock_response(status_code: int, body, method: str = "POST") -> httpx.Response:
    """Build a fake httpx.Response with a dummy request so raise_for_status() works."""
    content = json.dumps(body).encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        request=httpx.Request(method, "http://test"),
    )


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success():
    """Successful login stores token and expiry."""
    adapter = make_adapter()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response(200, TOKEN_RESPONSE)

        await adapter.authenticate()

    assert adapter._token == FAKE_TOKEN
    assert adapter._token_expires_at is not None
    assert adapter._token_expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_authenticate_accepts_access_token_field():
    """Should accept both 'token' and 'access_token' response shapes."""
    adapter = make_adapter()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response(
            200, {"access_token": FAKE_TOKEN, "expires_in": 1800}
        )

        await adapter.authenticate()

    assert adapter._token == FAKE_TOKEN


@pytest.mark.asyncio
async def test_authenticate_raises_on_missing_token_field():
    """Should raise RuntimeError if response has no recognisable token key."""
    adapter = make_adapter()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response(200, {"session": "xyz"})

        with pytest.raises(RuntimeError, match="token"):
            await adapter.authenticate()


@pytest.mark.asyncio
async def test_authenticate_uses_form_data_not_json():
    """POST /login must send form-encoded body, not JSON."""
    adapter = make_adapter()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response(200, TOKEN_RESPONSE)

        await adapter.authenticate()

    call_kwargs = mock_client.post.call_args[1]
    # Must use 'data=' (form), never 'json='
    assert "data" in call_kwargs, "authenticate() must use data= (form), not json="
    assert "json" not in call_kwargs, "authenticate() must not use json= body"
    form = call_kwargs["data"]
    assert form["username"] == USERNAME
    assert form["client_id"] == CLIENT_ID


@pytest.mark.asyncio
async def test_authenticate_skipped_when_token_valid():
    """Second call to authenticate() should not POST again if token still valid."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await adapter.authenticate()

    mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# get_projects / get_devices tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_projects_returns_list():
    """get_projects() fetches /data/projects and returns the parsed list."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response(200, PROJECTS, method="GET")

        result = await adapter.get_projects()

    assert result == PROJECTS
    call_url = mock_client.get.call_args[0][0]
    assert call_url.endswith("/data/projects")


@pytest.mark.asyncio
async def test_get_devices_returns_list():
    """get_devices() fetches /data/devices and returns the parsed list."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response(200, DEVICES, method="GET")

        result = await adapter.get_devices()

    assert len(result) == 3
    assert result[0]["id"] == "4664"


# ---------------------------------------------------------------------------
# 401/403 re-auth retry flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_json_retries_on_401():
    """A 401 response triggers one re-authentication and a second GET attempt."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    # First GET → 401; after re-auth, second GET → 200
    first_401 = mock_response(401, {"error": "Unauthorized"}, method="GET")
    second_ok = mock_response(200, PROJECTS, method="GET")

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Re-auth POST returns a new token
        mock_client.post.return_value = mock_response(200, TOKEN_RESPONSE)
        mock_client.get.side_effect = [first_401, second_ok]

        result = await adapter._get_json("/data/projects")

    assert result == PROJECTS
    # POST (re-auth) was called once
    mock_client.post.assert_called_once()
    # GET was called twice (first → 401, second → 200)
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_json_retries_on_403():
    """A 403 response also triggers re-authentication and retry."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    first_403 = mock_response(403, {"error": "Forbidden"}, method="GET")
    second_ok = mock_response(200, DEVICES, method="GET")

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response(200, TOKEN_RESPONSE)
        mock_client.get.side_effect = [first_403, second_ok]

        result = await adapter._get_json("/data/devices")

    assert result == DEVICES
    mock_client.post.assert_called_once()


# ---------------------------------------------------------------------------
# Probe provider interface tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_probes_maps_devices_to_metadata():
    """list_probes() returns one ProbeMetadataDTO per device."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch.object(adapter, "get_projects", AsyncMock(return_value=PROJECTS)):
        with patch.object(adapter, "get_devices", AsyncMock(return_value=DEVICES)):
            probes = await adapter.list_probes()

    assert len(probes) == 3
    external_ids = {p.external_id for p in probes}
    # devices have no project_id in API response → project_id part is empty string
    assert any("4664" in eid for eid in external_ids)
    assert any("4665" in eid for eid in external_ids)


@pytest.mark.asyncio
async def test_fetch_probe_metadata_returns_dto():
    """fetch_probe_metadata() returns correct DTO for a known device."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch.object(adapter, "get_devices", AsyncMock(return_value=DEVICES)):
        meta = await adapter.fetch_probe_metadata("1044/4664")

    assert meta.external_id == "1044/4664"
    assert meta.depths_cm == [40, 60]
    assert meta.manufacturer == "MyIrrigation"


@pytest.mark.asyncio
async def test_fetch_readings_maps_suction_sensors():
    """fetch_readings() parses the real columnar API format → soil_tension_cbar DTOs."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    since = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    until = datetime(2024, 6, 3, 23, 59, 59, tzinfo=UTC)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response(200, DEVICE_DATA_RESPONSE, method="POST")

        readings = await adapter.fetch_readings("1044/4664", since, until)

    # 2 sensors × 2 timestamps = 4 readings (battery excluded)
    assert len(readings) == 4
    assert all(r.unit == "soil_tension_cbar" for r in readings)
    assert all(r.sensor_type == "moisture" for r in readings)
    assert all(r.timestamp.tzinfo is not None for r in readings)

    # Depths extracted from sensor names "WM 40cm" and "WM 60cm"
    depths = {r.depth_cm for r in readings}
    assert depths == {40, 60}

    # Values from fixture
    readings_40 = [r for r in readings if r.depth_cm == 40]
    assert readings_40[0].raw_value == pytest.approx(45)
    assert readings_40[1].raw_value == pytest.approx(48)

    # Endpoint and form data assertions
    call_url = mock_client.post.call_args[0][0]
    assert "4664" in call_url
    assert "/data" in call_url
    call_kwargs = mock_client.post.call_args[1]
    assert "start_date" in call_kwargs.get("data", {})
    assert "end_date" in call_kwargs.get("data", {})


@pytest.mark.asyncio
async def test_fetch_readings_returns_empty_on_error():
    """fetch_readings() returns [] on API error — never raises."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    since = datetime(2024, 6, 1, tzinfo=UTC)
    until = datetime(2024, 6, 3, tzinfo=UTC)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        # fetch_readings now uses POST, so mock post (not get)
        mock_client.post.side_effect = httpx.ConnectError("connection refused")

        readings = await adapter.fetch_readings("1044/4664", since, until)

    assert readings == []


@pytest.mark.asyncio
async def test_fetch_readings_sends_form_date_params():
    """fetch_readings() POSTs start_date/end_date as form fields in API format."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    since = datetime(2024, 6, 1, 8, 0, 0, tzinfo=UTC)
    until = datetime(2024, 6, 3, 18, 0, 0, tzinfo=UTC)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response(200, {"success": True, "data": {"sensors": [], "datetimes": [], "values": {}}}, method="POST")

        await adapter.fetch_readings("1044/4664", since, until)

    call_kwargs = mock_client.post.call_args[1]
    form = call_kwargs["data"]
    assert form["start_date"] == "2024-06-01 08:00:00"
    assert form["end_date"] == "2024-06-03 18:00:00"


@pytest.mark.asyncio
async def test_fetch_forecast_uses_project_endpoint():
    """fetch_forecast() calls /data/projects/{project_id}/weather_forecast/detailed."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)
    adapter._project_id = "563"  # pre-set to avoid get_projects call

    forecast_response = [
        {
            "date": "2026-04-11",
            "temperature_max": 28.5,
            "temperature_min": 14.2,
            "humidity": 55.0,
            "rainfall": 0.0,
            "et0": 5.1,
        },
        {
            "date": "2026-04-12",
            "temperature_max": 30.1,
            "temperature_min": 15.0,
            "humidity": 48.0,
            "rainfall": 0.0,
            "et0": 5.8,
        },
    ]

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response(200, forecast_response, method="GET")

        forecasts = await adapter.fetch_forecast(38.42, -7.54, days=5)

    assert len(forecasts) == 2
    assert forecasts[0].temperature_max_c == pytest.approx(28.5)
    assert forecasts[0].et0_mm == pytest.approx(5.1)

    call_url = mock_client.get.call_args[0][0]
    assert "projects/563" in call_url
    assert "weather_forecast/detailed" in call_url


@pytest.mark.asyncio
async def test_fetch_forecast_auto_detects_project_id():
    """If project_id not configured, auto-detect from first project."""
    adapter = MyIrrigationAdapter(
        base_url=BASE_URL, username=USERNAME, password=PASSWORD,
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        project_id="",  # intentionally blank to test auto-detect
    )
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch.object(adapter, "get_projects", AsyncMock(return_value=[{"id": "1044", "name": "ESPORÃO OLIVAL"}])):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response(200, [], method="GET")

            await adapter.fetch_forecast(38.42, -7.54, days=3)

    # Project ID should now be cached
    assert adapter._project_id == "1044"


@pytest.mark.asyncio
async def test_post_form_json_retries_on_401():
    """A 401 on a POST also triggers re-auth and retry."""
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    first_401 = mock_response(401, {"error": "Unauthorized"}, method="POST")
    second_ok = mock_response(200, [], method="POST")

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.side_effect = [
            first_401,          # first device data POST → 401
            mock_response(200, TOKEN_RESPONSE),  # re-auth POST
            second_ok,          # second device data POST → 200
        ]

        result = await adapter._post_form_json("/data/devices/4664/data", {"start_date": "x", "end_date": "y"})

    assert result == []
    assert mock_client.post.call_count == 3  # 401 + re-auth + retry


@pytest.mark.asyncio
async def test_health_check_returns_true_on_success():
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch.object(adapter, "get_projects", AsyncMock(return_value=PROJECTS)):
        assert await adapter.health_check() is True


@pytest.mark.asyncio
async def test_health_check_returns_false_on_failure():
    adapter = make_adapter()
    adapter._token = FAKE_TOKEN
    adapter._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch.object(adapter, "get_projects", AsyncMock(side_effect=Exception("boom"))):
        assert await adapter.health_check() is False


# ---------------------------------------------------------------------------
# Factory wiring tests
# ---------------------------------------------------------------------------


def test_factory_get_probe_provider_myirrigation():
    """Factory returns a MyIrrigationAdapter for PROBE_PROVIDER=myirrigation."""
    from unittest.mock import MagicMock
    import app.adapters.factory as factory_module

    # Reset singleton to avoid cross-test contamination
    factory_module._myirrigation_instance = None

    from app.adapters.factory import get_probe_provider
    from app.adapters.myirrigation import MyIrrigationAdapter

    fake_settings = MagicMock()
    fake_settings.PROBE_PROVIDER = "myirrigation"
    fake_settings.MYIRRIGATION_BASE_URL = BASE_URL
    fake_settings.MYIRRIGATION_USERNAME = USERNAME
    fake_settings.MYIRRIGATION_PASSWORD = PASSWORD
    fake_settings.MYIRRIGATION_CLIENT_ID = CLIENT_ID
    fake_settings.MYIRRIGATION_CLIENT_SECRET = CLIENT_SECRET

    provider = get_probe_provider(fake_settings)
    assert isinstance(provider, MyIrrigationAdapter)

    # Clean up singleton
    factory_module._myirrigation_instance = None


def test_factory_get_weather_provider_myirrigation():
    """Factory returns a MyIrrigationAdapter for WEATHER_PROVIDER=myirrigation."""
    from unittest.mock import MagicMock
    import app.adapters.factory as factory_module

    factory_module._myirrigation_instance = None

    from app.adapters.factory import get_weather_provider
    from app.adapters.myirrigation import MyIrrigationAdapter

    fake_settings = MagicMock()
    fake_settings.WEATHER_PROVIDER = "myirrigation"
    fake_settings.MYIRRIGATION_BASE_URL = BASE_URL
    fake_settings.MYIRRIGATION_USERNAME = USERNAME
    fake_settings.MYIRRIGATION_PASSWORD = PASSWORD
    fake_settings.MYIRRIGATION_CLIENT_ID = CLIENT_ID
    fake_settings.MYIRRIGATION_CLIENT_SECRET = CLIENT_SECRET

    provider = get_weather_provider(fake_settings)
    assert isinstance(provider, MyIrrigationAdapter)

    factory_module._myirrigation_instance = None


def test_factory_raises_on_missing_credentials():
    """Factory raises ValueError when username/password are empty."""
    from unittest.mock import MagicMock
    import app.adapters.factory as factory_module

    factory_module._myirrigation_instance = None

    from app.adapters.factory import get_probe_provider

    fake_settings = MagicMock()
    fake_settings.PROBE_PROVIDER = "myirrigation"
    fake_settings.MYIRRIGATION_USERNAME = ""
    fake_settings.MYIRRIGATION_PASSWORD = ""

    with pytest.raises(ValueError, match="MYIRRIGATION_USERNAME"):
        get_probe_provider(fake_settings)

    factory_module._myirrigation_instance = None


def test_factory_raises_on_unknown_probe_provider():
    """Factory raises ValueError for unknown provider names."""
    from unittest.mock import MagicMock
    from app.adapters.factory import get_probe_provider

    fake_settings = MagicMock()
    fake_settings.PROBE_PROVIDER = "unknown_vendor"

    with pytest.raises(ValueError, match="Unknown probe provider"):
        get_probe_provider(fake_settings)


# ---------------------------------------------------------------------------
# Parsing helper unit tests
# ---------------------------------------------------------------------------


def test_parse_external_id_valid():
    project_id, device_id = _parse_external_id("proj-1/dev-101")
    assert project_id == "proj-1"
    assert device_id == "dev-101"


def test_parse_external_id_invalid():
    with pytest.raises(ValueError):
        _parse_external_id("no-slash-here")


def test_unix_ms_to_datetime_int():
    ts = _unix_ms_to_datetime(1717243200000)
    assert ts is not None
    assert ts.tzinfo is not None
    assert ts.year == 2024 and ts.month == 6 and ts.day == 1


def test_unix_ms_to_datetime_string():
    ts = _unix_ms_to_datetime("1717243200000")
    assert ts is not None
    assert ts.tzinfo is not None


def test_unix_ms_to_datetime_invalid():
    assert _unix_ms_to_datetime("not-a-number") is None
    assert _unix_ms_to_datetime(None) is None


def test_depth_from_sensor_name_standard():
    assert _depth_from_sensor_name("WM 40cm") == 40
    assert _depth_from_sensor_name("WM 60cm") == 60
    assert _depth_from_sensor_name("Soil 30CM") == 30


def test_depth_from_sensor_name_fallback():
    """No depth pattern → default 40cm."""
    assert _depth_from_sensor_name("Battery") == 40
    assert _depth_from_sensor_name("Solar Panel") == 40


def test_normalise_unit_cbar():
    assert _normalise_unit("cBar") == "soil_tension_cbar"
    assert _normalise_unit("cb") == "soil_tension_cbar"
    assert _normalise_unit("kpa") == "soil_tension_cbar"


def test_normalise_unit_vwc():
    assert _normalise_unit("m3/m3") == "vwc_m3m3"
    assert _normalise_unit("vwc") == "vwc_m3m3"


def test_parse_device_readings_extracts_suction():
    """_parse_device_readings() maps columnar Suction data to ProbeReadingDTOs."""
    result = _parse_device_readings(DEVICE_DATA_RESPONSE, "1044/4664")
    assert len(result) == 4  # 2 suction sensors × 2 timestamps
    assert all(r.unit == "soil_tension_cbar" for r in result)
    depths = {r.depth_cm for r in result}
    assert depths == {40, 60}


def test_parse_device_readings_ignores_battery():
    """Battery and Solar Panel sensors are not included in readings."""
    result = _parse_device_readings(DEVICE_DATA_RESPONSE, "1044/4664")
    # Only Suction sensors — Battery excluded
    assert all(r.sensor_type == "moisture" for r in result)


def test_parse_device_readings_negative_values_included():
    """Negative values are included (quality flagging happens in ingestion service)."""
    response = {
        "success": True,
        "data": {
            "sensors": [
                {"id": "17_0_0", "sensor_type": "Suction", "name": "WM 40cm", "units": "cBar"},
            ],
            "datetimes": [1717243200000],
            "values": {"17_0_0": {"1717243200000": -252}},
        }
    }
    result = _parse_device_readings(response, "1044/4664")
    assert len(result) == 1
    assert result[0].raw_value == -252.0


def test_get_float_first_matching_key():
    data = {"temp_max": 32.5, "tmax": 35.0}
    assert _get_float(data, "temp_max", "tmax") == pytest.approx(32.5)


def test_get_float_fallback_key():
    data = {"tmax": 35.0}
    assert _get_float(data, "temp_max", "tmax") == pytest.approx(35.0)


def test_get_float_none_when_absent():
    assert _get_float({}, "temp_max", "tmax") is None


def test_get_float_handles_string_numbers():
    assert _get_float({"et0": "5.2"}, "et0") == pytest.approx(5.2)
