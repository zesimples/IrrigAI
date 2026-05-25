# backend/tests/test_flowmeter/test_event_detector.py
from datetime import datetime, timedelta, timezone

from app.services.flowmeter_ingestion import IrrigationEventDetector

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
    # 6 readings at 15-min steps: indices 1-6 → t+15 to t+90, span = 75 min
    # + 1 interval (15 min) = 90 min total (last bucket contribution)
    readings = _make_readings([0, 1.5, 2.0, 2.0, 2.0, 2.0, 1.5, 0])
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    assert events[0].duration_minutes == 90.0


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


def test_value_exactly_at_threshold_does_not_open_event():
    # value == threshold is NOT > threshold, so no event opens
    readings = _make_readings([0, 0.5, 0.5, 0.5, 0])
    events = IrrigationEventDetector().detect_events(readings, threshold_m3_ha=0.5)
    assert len(events) == 0


def test_single_reading_duration_includes_interval():
    # Two readings at t=30 and t=45 (step 15): span = 15 min, + 1 interval = 30 min
    readings = _make_readings([0, 0, 2.5, 2.5, 0])
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    assert events[0].duration_minutes == 30.0


def test_two_readings_duration_includes_last_interval():
    # readings at t=0, t=15, t=30: span = 30 min + interval = 45 min
    readings = [(_ts(0), 2.0), (_ts(15), 3.0), (_ts(30), 2.5)]
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    assert events[0].duration_minutes == 45.0


def test_event_splits_across_large_gap():
    # gap of 90 min between t=30 and t=120 is > 15 * 2.5 = 37.5 min → 2 events
    readings = [
        (_ts(0), 2.0), (_ts(15), 3.0), (_ts(30), 2.5),
        (_ts(120), 1.8), (_ts(135), 2.1),
    ]
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 2
    assert events[0].num_readings == 3
    assert events[1].num_readings == 2


def test_small_gap_does_not_split_event():
    # gap of 30 min between t=15 and t=45 — 30 / 15 = 2.0 which is NOT > 2.5 → 1 event
    readings = [
        (_ts(0), 2.0), (_ts(15), 3.0),
        (_ts(45), 1.8), (_ts(60), 2.1),
    ]
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1


def test_below_minimum_consumption_no_event():
    # values 0.3 < threshold 0.5 → no event
    readings = _make_readings([0, 0.3, 0.3, 0.3, 0])
    events = IrrigationEventDetector().detect_events(readings, threshold_m3_ha=0.5)
    assert len(events) == 0
