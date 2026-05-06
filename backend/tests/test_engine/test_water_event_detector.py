from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.engine.water_event_detector import _Candidate, _build_candidates, _score_group
from app.schemas.probe import DepthReadings, TimeSeriesPoint


def _point(timestamp: datetime, vwc: float, quality: str = "ok") -> TimeSeriesPoint:
    return TimeSeriesPoint(timestamp=timestamp, vwc=vwc, quality=quality)


def test_build_candidates_uses_dynamic_noise_threshold():
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    readings = [
        _point(start + timedelta(hours=0), 0.210),
        _point(start + timedelta(hours=1), 0.211),
        _point(start + timedelta(hours=2), 0.210),
        _point(start + timedelta(hours=3), 0.212),
        _point(start + timedelta(hours=4), 0.211),
        _point(start + timedelta(hours=5), 0.228),
    ]

    candidates = _build_candidates([DepthReadings(depth_cm=30, readings=readings)])

    assert len(candidates) == 1
    assert candidates[0].depth_cm == 30
    assert candidates[0].delta_vwc >= 0.015


def test_score_group_prefers_recorded_irrigation_when_source_and_sequence_match():
    event_time = datetime(2026, 5, 1, 10, tzinfo=timezone.utc)
    group = [
        _Candidate(event_time, 20, 0.032, 0.008, 1.0, "ok"),
        _Candidate(event_time + timedelta(hours=2), 40, 0.026, 0.008, 1.0, "ok"),
    ]
    irrigation = SimpleNamespace(
        start_time=event_time - timedelta(minutes=30),
        applied_mm=8.0,
    )

    event = _score_group(
        group=group,
        index=0,
        total_depth_count=2,
        irrigation_events=[irrigation],
        weather_events=[],
    )

    assert event is not None
    assert event.kind == "irrigation"
    assert event.confidence == "high"
    assert event.probability_irrigation > event.probability_rain
    assert event.depth_sequence_score == 1.0


def test_score_group_prefers_rain_when_weather_source_matches_without_irrigation():
    event_time = datetime(2026, 5, 1, 10, tzinfo=timezone.utc)
    group = [
        _Candidate(event_time, 20, 0.030, 0.008, 1.0, "ok"),
        _Candidate(event_time + timedelta(hours=1), 40, 0.024, 0.008, 1.0, "ok"),
    ]
    rain = SimpleNamespace(timestamp=event_time, rainfall_mm=12.0)

    event = _score_group(
        group=group,
        index=0,
        total_depth_count=2,
        irrigation_events=[],
        weather_events=[rain],
    )

    assert event is not None
    assert event.kind == "rain"
    assert event.confidence == "high"
    assert event.probability_rain > event.probability_irrigation
