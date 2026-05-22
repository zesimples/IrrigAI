# backend/tests/test_flowmeter/test_event_detector.py
from datetime import datetime, timedelta, timezone

import pytest

from app.services.flowmeter_ingestion import DetectedEvent, IrrigationEventDetector

BASE_TIME = datetime(2026, 7, 15, 6, 0, 0, tzinfo=timezone.utc)


def _ts(minutes: int) -> datetime:
    return BASE_TIME + timedelta(minutes=minutes)


def _make_readings(values: list[float], step_minutes: int = 15) -> list[tuple[datetime, float]]:
    return [(_ts(i * step_minutes), v) for i, v in enumerate(values)]


def test_detect_single_event():
    readings = _make_readings([0, 0, 1.8, 3.0, 3.0, 2.9, 2.9, 1.1, 0, 0])
    detector = IrrigationEventDetector()
    events = detector.detect_events(readings)
    assert len(events) == 1
    e = events[0]
    assert e.num_readings == 6
    assert abs(e.total_m3_ha - (1.8 + 3.0 + 3.0 + 2.9 + 2.9 + 1.1)) < 0.01
    assert e.peak_m3_ha == 3.0
    assert e.start_time == _ts(30)  # index 2
    assert e.end_time == _ts(105)   # index 7


def test_detect_two_separate_events():
    # event 1 at positions 2-4, event 2 at positions 7-9
    readings = _make_readings([0, 0, 1.8, 3.0, 1.1, 0, 0, 2.0, 3.0, 1.5, 0])
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 2


def test_single_reading_event_is_discarded():
    readings = _make_readings([0, 0, 3.0, 0, 0])  # only one non-zero
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 0


def test_empty_readings():
    assert IrrigationEventDetector().detect_events([]) == []


def test_all_zeros():
    readings = _make_readings([0.0, 0.0, 0.0, 0.0])
    assert IrrigationEventDetector().detect_events(readings) == []


def test_duration_is_correct():
    # 6 readings × 15 min = start→end span of 75 min
    readings = _make_readings([0, 1.5, 2.0, 2.0, 2.0, 2.0, 1.5, 0])
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    assert events[0].duration_minutes == 75.0


def test_event_open_at_end_of_data_is_included():
    # data ends while event is still ongoing — should still be captured
    readings = _make_readings([0, 1.8, 3.0, 2.9])
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    assert events[0].num_readings == 3


def test_custom_threshold():
    readings = _make_readings([0, 0.3, 0.4, 0.6, 0.7, 0.3, 0])
    events = IrrigationEventDetector().detect_events(readings, threshold_m3_ha=0.5)
    assert len(events) == 1
    assert events[0].num_readings == 2
