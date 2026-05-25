# backend/tests/test_flowmeter/test_flowmeter_checker.py
"""Tests for FlowmeterAlertChecker — outlier stripping and deviation logic."""
from datetime import date, datetime, timezone

import pytest
from unittest.mock import MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_event(fm_id: str, start_dt: datetime, total_m3_ha: float) -> MagicMock:
    """Create a mock IrrigationEventDetected."""
    e = MagicMock()
    e.flowmeter_id = fm_id
    e.start_time = start_dt
    e.total_m3_ha = total_m3_ha
    e.date = start_dt.date()
    return e


def _make_pair(fm_id: str, sector_id: str, sector_name: str, crop_type: str):
    """Create a mock (Flowmeter, Sector) pair."""
    fm = MagicMock()
    fm.id = fm_id
    sector = MagicMock()
    sector.id = sector_id
    sector.name = sector_name
    sector.crop_type = crop_type
    return (fm, sector)


def _day_events(fm_id: str, day: date, values: list) -> list:
    """Create events for a single day at 06:00, 07:00, … one per value."""
    return [
        _make_event(
            fm_id,
            datetime(day.year, day.month, day.day, 6 + i, 0, tzinfo=timezone.utc),
            v,
        )
        for i, v in enumerate(values)
    ]


BASE_DATE = date(2026, 5, 18)


def _days(n: int) -> list:
    from datetime import timedelta
    return [BASE_DATE + timedelta(days=i) for i in range(n)]


# ── enum / schema smoke tests ─────────────────────────────────────────────────

def test_flowmeter_deviation_alert_type_value():
    from app.core.enums import AlertType
    assert AlertType.FLOWMETER_DEVIATION == "flowmeter_deviation"


def test_flowmeter_insufficient_data_alert_type_value():
    from app.core.enums import AlertType
    assert AlertType.FLOWMETER_INSUFFICIENT_DATA == "flowmeter_insufficient_data"


def test_flowmeter_deviations_response_schema_constructs():
    from app.schemas.flowmeter import FlowmeterDeviationsResponse
    r = FlowmeterDeviationsResponse(
        period_days=7,
        deviating=[],
        insufficient_data=[],
        crop_averages={},
        evaluated_at=datetime.now(timezone.utc),
    )
    assert r.period_days == 7
    assert r.deviating == []
