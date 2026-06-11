"""Unit tests for FlowmeterFlowRateAlertChecker — no DB required."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.alerts.flowmeter_flow_rate_alerts import FlowmeterFlowRateAlertChecker
from app.core.enums import AlertSeverity, AlertType

T0 = datetime(2026, 6, 11, 6, 0, tzinfo=UTC)

FARM_ID = "farm-001"
SECTOR_ID = "sec-001"
SECTOR_NAME = "S02 Amendoal"


def _reference(rate: float = 2.89, tol: float = 5.0) -> MagicMock:
    ref = MagicMock()
    ref.reference_rate_m3_ha = rate
    ref.tolerance_pct = tol
    ref.upper_limit_m3_ha = round(rate * (1 + tol / 100), 4)
    ref.lower_limit_m3_ha = round(rate * (1 - tol / 100), 4)
    ref.status = "established"
    return ref


def _readings(plateau_value: float, count: int = 9) -> list[tuple[datetime, float]]:
    ramp_up = [1.0, 1.5]
    plateau = [plateau_value] * (count - 4)
    ramp_down = [1.2, 0.5]
    all_vals = ramp_up + plateau + ramp_down
    return [(T0 + timedelta(minutes=i * 15), v) for i, v in enumerate(all_vals)]


# ─── _check_event_rate ────────────────────────────────────────────────────────

def test_rate_above_tolerance_generates_high_alert():
    checker = FlowmeterFlowRateAlertChecker()
    ref = _reference(rate=2.89, tol=5.0)
    # 3.07 / 2.89 = 6.2% above
    alert = checker._check_event_rate(3.07, ref, SECTOR_NAME, SECTOR_ID, FARM_ID, T0)
    assert alert is not None
    assert alert.alert_type == AlertType.FLOWMETER_FLOW_RATE_HIGH
    assert alert.severity == AlertSeverity.WARNING
    assert "S02" in alert.title_pt
    assert alert.data["deviation_pct"] > 5.0


def test_rate_below_tolerance_generates_low_alert():
    checker = FlowmeterFlowRateAlertChecker()
    ref = _reference(rate=2.89, tol=5.0)
    # 2.72 / 2.89 = -5.9% below
    alert = checker._check_event_rate(2.72, ref, SECTOR_NAME, SECTOR_ID, FARM_ID, T0)
    assert alert is not None
    assert alert.alert_type == AlertType.FLOWMETER_FLOW_RATE_LOW
    assert alert.data["deviation_pct"] < -5.0


def test_rate_within_tolerance_returns_none():
    checker = FlowmeterFlowRateAlertChecker()
    ref = _reference(rate=2.89, tol=5.0)
    # 2.90 is within 5% of 2.89
    alert = checker._check_event_rate(2.90, ref, SECTOR_NAME, SECTOR_ID, FARM_ID, T0)
    assert alert is None


def test_insufficient_reference_returns_none():
    checker = FlowmeterFlowRateAlertChecker()
    ref = _reference()
    ref.status = "insufficient"
    alert = checker._check_event_rate(3.20, ref, SECTOR_NAME, SECTOR_ID, FARM_ID, T0)
    assert alert is None


# ─── _detect_mid_event_zeros ─────────────────────────────────────────────────

def test_mid_event_zeros_generates_info_alert():
    checker = FlowmeterFlowRateAlertChecker()
    zero_threshold = 0.1
    raw = list(_readings(2.9, count=9))
    # Replace readings 3 and 4 (plateau) with zeros
    raw[3] = (raw[3][0], 0.0)
    raw[4] = (raw[4][0], 0.0)
    alert = checker._detect_mid_event_zeros(
        raw, SECTOR_NAME, SECTOR_ID, FARM_ID, T0, zero_threshold=zero_threshold
    )
    assert alert is not None
    assert alert.alert_type == AlertType.FLOWMETER_MID_EVENT_ZEROS
    assert alert.severity == AlertSeverity.INFO
    assert alert.data["zero_count"] == 2


def test_no_mid_event_zeros_returns_none():
    checker = FlowmeterFlowRateAlertChecker()
    raw = list(_readings(2.9, count=9))
    alert = checker._detect_mid_event_zeros(
        raw, SECTOR_NAME, SECTOR_ID, FARM_ID, T0
    )
    assert alert is None
