"""Unit tests for irrigation anomaly detection rules."""

from datetime import UTC, datetime, timedelta

import pytest

from app.anomaly.rules.irrigation_rules import (
    detect_irrigation_underperformance,
    detect_over_irrigation,
)
from app.anomaly.rules.sensor_rules import Reading


def make_event(applied: float, recommended: float, at: datetime | None = None) -> dict:
    return {
        "applied_mm": applied,
        "recommended_mm": recommended,
        "event_at": at or datetime(2024, 6, 1, 8, 0, tzinfo=UTC),
    }


def make_readings(values: list[float], start: datetime | None = None, interval_h: float = 1.0) -> list[Reading]:
    if start is None:
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
    return [
        Reading(timestamp=start + timedelta(hours=i * interval_h), vwc=v)
        for i, v in enumerate(values)
    ]


SEC = "sector-1"
PRB = "probe-1"


class TestDetectIrrigationUnderperformance:
    def test_three_consecutive_underperforming_events(self):
        base = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        events = [
            make_event(applied=5.0, recommended=10.0, at=base + timedelta(days=i))
            for i in range(3)
        ]
        result = detect_irrigation_underperformance(events, SEC)
        assert len(result) == 1
        assert result[0].anomaly_type == "irrigation_underperformance"
        assert result[0].severity == "warning"

    def test_one_event_no_anomaly(self):
        events = [make_event(5.0, 10.0)]
        result = detect_irrigation_underperformance(events, SEC)
        assert result == []

    def test_two_events_no_anomaly(self):
        events = [make_event(5.0, 10.0), make_event(5.0, 10.0)]
        result = detect_irrigation_underperformance(events, SEC)
        assert result == []

    def test_ok_events_no_anomaly(self):
        """Applied ≥ 70% of recommended → no anomaly."""
        base = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        events = [
            make_event(applied=8.0, recommended=10.0, at=base + timedelta(days=i))
            for i in range(5)
        ]
        result = detect_irrigation_underperformance(events, SEC)
        assert result == []

    def test_intermixed_events_resets_run(self):
        """Good event between bad ones resets the consecutive run counter."""
        base = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        events = [
            make_event(5.0, 10.0, base),                      # bad
            make_event(5.0, 10.0, base + timedelta(days=1)),   # bad
            make_event(9.0, 10.0, base + timedelta(days=2)),   # good → reset
            make_event(5.0, 10.0, base + timedelta(days=3)),   # bad
            make_event(5.0, 10.0, base + timedelta(days=4)),   # bad
        ]
        result = detect_irrigation_underperformance(events, SEC)
        # Only 2 bad events after reset — no anomaly
        assert result == []

    def test_four_consecutive_bad_events(self):
        base = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        events = [
            make_event(5.0, 10.0, base + timedelta(days=i))
            for i in range(4)
        ]
        result = detect_irrigation_underperformance(events, SEC)
        assert len(result) == 1
        assert result[0].data_context["n_events"] == 4


class TestDetectOverIrrigation:
    def test_deep_layer_responds_to_irrigation(self):
        # irrig_start at 8:30 — so the 8:00 reading is "before" and 9:00 is "after"
        irrig_start = datetime(2024, 6, 1, 8, 30, tzinfo=UTC)
        before_start = datetime(2024, 6, 1, 6, 0, tzinfo=UTC)

        shallow = make_readings([0.20, 0.20, 0.28, 0.27], start=before_start)
        # Deep: 6:00=0.22, 7:00=0.22, 8:00=0.22 (before irrig at 8:30), 9:00=0.27 (after, +0.05)
        deep = make_readings([0.22, 0.22, 0.22, 0.27], start=before_start)

        result = detect_over_irrigation(shallow, deep, irrig_start, SEC, PRB)
        assert len(result) == 1
        assert result[0].anomaly_type == "over_irrigation"

    def test_no_deep_response_no_anomaly(self):
        irrig_start = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        before_start = datetime(2024, 6, 1, 6, 0, tzinfo=UTC)

        shallow = make_readings([0.20, 0.20, 0.28, 0.27], start=before_start)
        deep = make_readings([0.22, 0.22, 0.22, 0.22], start=before_start)

        result = detect_over_irrigation(shallow, deep, irrig_start, SEC, PRB)
        assert result == []

    def test_empty_deep_readings_no_anomaly(self):
        irrig_start = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        shallow = make_readings([0.20, 0.28])
        result = detect_over_irrigation(shallow, [], irrig_start, SEC, PRB)
        assert result == []
