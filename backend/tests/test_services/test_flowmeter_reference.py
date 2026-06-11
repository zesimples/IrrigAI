"""Unit tests for stable flow rate computation — no DB required."""
from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

import pytest

from app.services.flowmeter_reference import (
    compute_stable_flow_rate,
    compute_reference_from_stable_rates,
    StableRateResult,
    MIN_EVENTS_ESTABLISHED,
    MIN_EVENTS_PROVISIONAL,
)

T0 = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)


def readings(values: list[float], interval_minutes: int = 15) -> list[tuple[datetime, float]]:
    return [(T0 + timedelta(minutes=i * interval_minutes), v) for i, v in enumerate(values)]


# ─── compute_stable_flow_rate ─────────────────────────────────────────────────

def test_stable_rate_trims_ramp_up_and_ramp_down():
    # 9 readings: ramp-up (1.0, 1.5), plateau (2.9, 3.0, 3.1, 2.9, 3.0), ramp-down (1.2, 0.5)
    r = readings([1.0, 1.5, 2.9, 3.0, 3.1, 2.9, 3.0, 1.2, 0.5])
    result = compute_stable_flow_rate(r)
    assert result.status == "ok"
    assert result.num_readings_used == 5
    expected = statistics.mean([2.9, 3.0, 3.1, 2.9, 3.0])
    assert abs(result.stable_rate_m3_ha - expected) < 0.001


def test_stable_rate_too_short_after_trim():
    # 4 readings: trim 2+2 leaves 0 — too short
    r = readings([1.0, 2.9, 3.0, 0.5])
    result = compute_stable_flow_rate(r)
    assert result.status == "too_short"
    assert result.stable_rate_m3_ha is None


def test_stable_rate_exact_minimum():
    # 7 readings: trim 2+2 leaves 3 — exactly the minimum
    r = readings([1.0, 1.5, 2.9, 3.0, 3.1, 1.2, 0.5])
    result = compute_stable_flow_rate(r)
    assert result.status == "ok"
    assert result.num_readings_used == 3


def test_stable_rate_custom_trim():
    r = readings([1.0, 2.9, 3.0, 3.1, 0.5])
    result = compute_stable_flow_rate(r, trim_start=1, trim_end=1)
    assert result.status == "ok"
    assert result.num_readings_used == 3
    assert abs(result.stable_rate_m3_ha - statistics.mean([2.9, 3.0, 3.1])) < 0.001


def test_stable_rate_empty_input():
    result = compute_stable_flow_rate([])
    assert result.status == "too_short"


def test_stable_rate_sorts_by_timestamp():
    # Provide readings out of order — function must sort
    r = [
        (T0 + timedelta(minutes=45), 3.0),
        (T0, 1.0),
        (T0 + timedelta(minutes=15), 1.5),
        (T0 + timedelta(minutes=30), 2.9),
        (T0 + timedelta(minutes=60), 3.1),
        (T0 + timedelta(minutes=75), 1.2),
        (T0 + timedelta(minutes=90), 0.5),
    ]
    result = compute_stable_flow_rate(r)
    assert result.status == "ok"
    assert result.num_readings_used == 3


# ─── compute_reference_from_stable_rates ─────────────────────────────────────

def test_reference_established_from_five_or_more_events():
    rates = [2.89, 2.92, 2.88, 2.91, 2.87, 2.90]
    ref = compute_reference_from_stable_rates(rates)
    assert ref["status"] == "established"
    assert ref["num_events"] == 6
    expected = statistics.median(rates)
    assert abs(ref["reference_rate_m3_ha"] - expected) < 0.001


def test_reference_provisional_from_three_or_four_events():
    rates = [2.89, 2.92, 2.88, 2.91]
    ref = compute_reference_from_stable_rates(rates)
    assert ref["status"] == "provisional"


def test_reference_insufficient_below_three():
    rates = [2.89, 2.92]
    ref = compute_reference_from_stable_rates(rates)
    assert ref["status"] == "insufficient"
    assert ref["reference_rate_m3_ha"] is None


def test_reference_computes_limits():
    rates = [2.90] * 6  # median = 2.90, tol = 5%
    ref = compute_reference_from_stable_rates(rates, tolerance_pct=5.0)
    assert abs(ref["upper_limit_m3_ha"] - 2.90 * 1.05) < 0.001
    assert abs(ref["lower_limit_m3_ha"] - 2.90 * 0.95) < 0.001


# ─── FlowmeterReferenceService (DB mocked) ────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.flowmeter_reference import FlowmeterReferenceService

FM_ID = "fm-001"
SECTOR_ID = "sec-001"
SECTOR_NAME = "S02 Amendoal"


def _mock_event(start_offset_h: int, end_offset_h: int) -> MagicMock:
    ev = MagicMock()
    ev.id = f"ev-{start_offset_h}"
    ev.start_time = T0 + timedelta(hours=start_offset_h)
    ev.end_time = T0 + timedelta(hours=end_offset_h)
    return ev


def _mock_readings_for_event(
    start_time: datetime, count: int, plateau_value: float = 2.9
) -> list[MagicMock]:
    ramp_up = [1.0, 1.5]
    plateau = [plateau_value] * (count - 4)
    ramp_down = [1.2, 0.5]
    all_vals = ramp_up + plateau + ramp_down
    result = []
    for i, v in enumerate(all_vals):
        r = MagicMock()
        r.timestamp = start_time + timedelta(minutes=i * 15)
        r.value_m3_ha = v
        result.append(r)
    return result


@pytest.mark.asyncio
async def test_compute_reference_returns_established_status():
    svc = FlowmeterReferenceService()

    # Build 6 mock events
    events = [_mock_event(i * 24, i * 24 + 6) for i in range(6)]
    readings_per_event = {
        ev.id: _mock_readings_for_event(ev.start_time, count=9, plateau_value=2.9)
        for ev in events
    }

    db = AsyncMock()

    with patch.object(svc, "_load_events", new=AsyncMock(return_value=events)), \
         patch.object(svc, "_load_readings_for_event") as mock_load:
        async def load_readings(event, db):
            return readings_per_event.get(
                event.id, _mock_readings_for_event(event.start_time, count=9)
            )
        mock_load.side_effect = load_readings
        ref = await svc.compute_reference(FM_ID, SECTOR_ID, SECTOR_NAME, db=db, lookback_days=30)

    assert ref.status == "established"
    assert ref.num_events_analyzed == 6
    assert ref.reference_rate_m3_ha is not None
    assert ref.reference_rate_m3_ha > 2.0


@pytest.mark.asyncio
async def test_compute_reference_returns_insufficient_when_few_events():
    svc = FlowmeterReferenceService()
    db = AsyncMock()

    with patch.object(svc, "_load_events", new=AsyncMock(return_value=[_mock_event(0, 6), _mock_event(24, 30)])), \
         patch.object(svc, "_load_readings_for_event") as mock_load:
        async def load_readings(event, db):
            return _mock_readings_for_event(event.start_time, count=9)
        mock_load.side_effect = load_readings
        ref = await svc.compute_reference(FM_ID, SECTOR_ID, SECTOR_NAME, db=db, lookback_days=30)

    assert ref.status == "insufficient"
    assert ref.reference_rate_m3_ha == 0.0
