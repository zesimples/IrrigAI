# backend/tests/test_flowmeter/test_parse_flowmeter_data.py
from datetime import datetime, timezone

from app.adapters.myirrigation import parse_flowmeter_data


_SAMPLE_RESPONSE = {
    "success": True,
    "data": {
        "sensors": [
            {
                "id": "0_0_0",
                "sensor_type": "Water Meter",
                "name": "Aplicação de Rega (m3/ha)",
                "units": "m3/ha",
            }
        ],
        "datetimes": [1778803200000, 1778804100000, 1778805000000],
        "values": {
            "0_0_0": {
                "1778803200000": 0,
                "1778804100000": 0,
                "1778805000000": 1.8,
            }
        },
    },
}


def test_parse_returns_timestamp_value_pairs():
    result = parse_flowmeter_data(_SAMPLE_RESPONSE, device_id=6980)
    assert len(result) == 3
    ts, val = result[2]
    assert isinstance(ts, datetime)
    assert ts.tzinfo == timezone.utc
    assert val == 1.8


def test_parse_returns_sorted_by_timestamp():
    # Timestamps intentionally out of order to exercise the sort
    raw = {
        "data": {
            "sensors": [{"id": "0_0_0", "sensor_type": "Water Meter", "units": "m3/ha"}],
            "values": {
                "0_0_0": {
                    "1778805000000": 1.8,  # latest first
                    "1778803200000": 0.0,
                    "1778804100000": 0.0,
                }
            },
        }
    }
    result = parse_flowmeter_data(raw, device_id=6980)
    timestamps = [r[0] for r in result]
    assert timestamps == sorted(timestamps)


def test_parse_skips_null_values():
    raw = {
        "data": {
            "sensors": [{"id": "0_0_0", "sensor_type": "Water Meter", "units": "m3/ha"}],
            "values": {"0_0_0": {"1778803200000": None, "1778804100000": 1.5}},
        }
    }
    result = parse_flowmeter_data(raw, device_id=6980)
    assert len(result) == 1
    assert result[0][1] == 1.5


def test_parse_returns_empty_if_no_water_meter_sensor():
    raw = {
        "data": {
            "sensors": [{"id": "1_0_0", "sensor_type": "Suction", "units": "cBar"}],
            "values": {"1_0_0": {"1778803200000": 42}},
        }
    }
    assert parse_flowmeter_data(raw, device_id=6980) == []


def test_parse_returns_empty_on_malformed_response():
    assert parse_flowmeter_data({}, device_id=6980) == []
    assert parse_flowmeter_data(None, device_id=6980) == []  # type: ignore[arg-type]
