from datetime import UTC, datetime, timedelta

import pytest

from app.engine.water_event_detector import (
    _build_candidates,
    _group_candidates,
    _score_group,
    detect_water_events,
)
from app.schemas.probe import DepthReadings, TimeSeriesPoint


def _point(timestamp: datetime, vwc: float, quality: str = "ok") -> TimeSeriesPoint:
    return TimeSeriesPoint(timestamp=timestamp, vwc=vwc, quality=quality)


def _depth(start: datetime, depth_cm: int, values: list[float]) -> DepthReadings:
    return DepthReadings(
        depth_cm=depth_cm,
        readings=[
            _point(start + timedelta(hours=index), value) for index, value in enumerate(values)
        ],
    )


def test_build_candidates_detects_cumulative_rise_from_local_baseline():
    start = datetime(2026, 5, 1, tzinfo=UTC)
    depth = _depth(
        start,
        30,
        [0.200, 0.199, 0.200, 0.201, 0.204, 0.207, 0.211, 0.210],
    )

    candidates = _build_candidates([depth])

    assert len(candidates) == 1
    assert candidates[0].depth_cm == 30
    assert candidates[0].timestamp == start + timedelta(hours=4)
    assert candidates[0].delta_vwc == pytest.approx(0.012)


def test_build_candidates_rejects_an_isolated_spike():
    start = datetime(2026, 5, 1, tzinfo=UTC)
    depth = _depth(start, 20, [0.200, 0.199, 0.200, 0.214, 0.200, 0.199])

    assert _build_candidates([depth]) == []


def test_two_same_depth_rises_are_not_merged_into_one_event():
    start = datetime(2026, 5, 1, tzinfo=UTC)
    depth = _depth(
        start,
        20,
        [0.200, 0.199, 0.207, 0.210, 0.209, 0.203, 0.210, 0.214, 0.213],
    )

    candidates = _build_candidates([depth])
    groups = _group_candidates(candidates)

    assert len(candidates) == 2
    assert len(groups) == 2
    assert candidates[0].delta_vwc == pytest.approx(0.011)
    assert candidates[1].delta_vwc == pytest.approx(0.011)


@pytest.mark.asyncio
async def test_delayed_multi_depth_response_is_grouped_as_probe_only_water_entry():
    start = datetime(2026, 5, 1, tzinfo=UTC)
    shallow = _depth(
        start,
        20,
        [0.200, 0.199, 0.207, 0.212, 0.211, 0.210, 0.209],
    )
    deep = _depth(
        start,
        40,
        [0.220, 0.219, 0.220, 0.221, 0.228, 0.233, 0.232],
    )

    events = await detect_water_events(
        depths=[shallow, deep],
        since=start,
        until=start + timedelta(hours=8),
    )

    assert len(events) == 1
    assert events[0].kind == "unlogged"
    assert events[0].depths_cm == [20, 40]
    assert events[0].delta_vwc == pytest.approx(0.027)
    assert events[0].probability_irrigation == 0
    assert events[0].probability_rain == 0
    assert "Entrada de água provável" in events[0].message


def test_irregular_cadence_lowers_sensor_quality_score():
    event_time = datetime(2026, 5, 1, 10, tzinfo=UTC)
    regular = _build_candidates([_depth(event_time, 20, [0.200, 0.199, 0.207, 0.212, 0.211])])[0]
    irregular_depth = DepthReadings(
        depth_cm=20,
        readings=[
            _point(event_time, 0.200),
            _point(event_time + timedelta(hours=1), 0.199),
            _point(event_time + timedelta(hours=20), 0.207),
            _point(event_time + timedelta(hours=21), 0.212),
            _point(event_time + timedelta(hours=22), 0.211),
        ],
    )
    irregular = _build_candidates([irregular_depth])[0]

    regular_event = _score_group([regular], 0, 1)
    irregular_event = _score_group([irregular], 0, 1)

    assert regular_event is not None
    assert irregular_event is not None
    assert irregular_event.sensor_quality_score < regular_event.sensor_quality_score
    assert irregular_event.score < regular_event.score
