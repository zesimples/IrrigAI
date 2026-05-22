# backend/tests/test_flowmeter/test_analytics.py
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

BASE_TIME = datetime(2026, 5, 22, 6, 0, 0, tzinfo=timezone.utc)


def _make_event(
    start_offset_days: int = 0,
    start_hour: int = 6,
    total_m3_ha: float = 18.0,
    duration_minutes: float = 90.0,
) -> MagicMock:
    start = (BASE_TIME + timedelta(days=start_offset_days)).replace(hour=start_hour)
    ev = MagicMock()
    ev.start_time = start
    ev.end_time = start + timedelta(minutes=duration_minutes)
    ev.total_m3_ha = total_m3_ha
    ev.duration_minutes = duration_minutes
    ev.date = start.date()
    ev.flowmeter_id = "test-fm-id"
    return ev


class TestComputePattern:
    def test_insufficient_data_two_events(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        events = [_make_event(0), _make_event(2)]
        pattern, score = svc._compute_pattern(events, date(2026, 5, 22))
        assert pattern == "insufficient_data"
        assert score == 0.0

    def test_insufficient_data_empty(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        pattern, score = svc._compute_pattern([], date(2026, 5, 22))
        assert pattern == "insufficient_data"
        assert score == 0.0

    def test_stopped_no_irrigation_in_5_days(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        # Events all around BASE_TIME (May 22). Today is June 1 → 10 days since last event.
        events = [_make_event(0), _make_event(1), _make_event(2)]
        today = date(2026, 6, 1)
        pattern, score = svc._compute_pattern(events, today)
        assert pattern == "stopped"
        assert score == 0.0

    def test_not_stopped_outside_apr_oct(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        # Events in May; today is December → outside Apr-Oct, not "stopped"
        events = [_make_event(0), _make_event(1), _make_event(2)]
        today = date(2026, 12, 15)
        pattern, score = svc._compute_pattern(events, today)
        assert pattern != "stopped"

    def test_regular_uniform_events(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        # Every 2 days, same volume → regular
        events = [_make_event(i * 2, total_m3_ha=18.0) for i in range(5)]
        pattern, score = svc._compute_pattern(events, date(2026, 5, 22))
        assert pattern == "regular"
        assert score >= 0.8

    def test_irregular_high_interval_variance(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        # Gaps: 1d, 7d, 1d, 7d — high std
        events = [_make_event(0), _make_event(1), _make_event(8), _make_event(9), _make_event(16)]
        pattern, score = svc._compute_pattern(events, date(2026, 6, 8))
        assert pattern == "irregular"
        assert score < 0.7


class TestSectorAnalyticsFromEvents:
    def test_no_events(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        result = svc._sector_analytics_from_events(
            sector_id="s1",
            sector_name="S01 Amendoal",
            crop_type="almond",
            events=[],
            period_start=date(2026, 5, 15),
            period_end=date(2026, 5, 22),
        )
        assert result.num_events == 0
        assert result.total_m3_ha == 0.0
        assert result.pattern == "insufficient_data"
        assert result.vs_crop_avg_pct is None

    def test_three_uniform_events(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        events = [_make_event(i * 2, total_m3_ha=18.0) for i in range(3)]
        result = svc._sector_analytics_from_events(
            sector_id="s1",
            sector_name="S01 Amendoal",
            crop_type="almond",
            events=events,
            period_start=date(2026, 5, 22),
            period_end=date(2026, 5, 29),
        )
        assert result.num_events == 3
        assert abs(result.total_m3_ha - 54.0) < 0.01
        assert abs(result.avg_m3_ha_per_event - 18.0) < 0.01
        assert result.typical_start_hour == 6
        assert result.vs_crop_avg_pct is None  # filled in by farm-level

    def test_consistency_score_high_for_uniform(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        events = [_make_event(i * 2, total_m3_ha=18.0) for i in range(5)]
        result = svc._sector_analytics_from_events(
            sector_id="s1", sector_name="S01", crop_type="almond",
            events=events, period_start=date(2026, 5, 1), period_end=date(2026, 5, 22),
        )
        assert result.consistency_score > 0.8

    def test_consistency_score_low_for_variable_volumes(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        # Volume alternates 3 m³/ha and 30 m³/ha — very variable
        events = [_make_event(i * 2, total_m3_ha=v) for i, v in enumerate([3.0, 30.0, 3.0, 30.0, 3.0])]
        result = svc._sector_analytics_from_events(
            sector_id="s1", sector_name="S01", crop_type="almond",
            events=events, period_start=date(2026, 5, 1), period_end=date(2026, 5, 22),
        )
        assert result.consistency_score < 0.7

    def test_daily_breakdown_is_complete(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        events = [_make_event(0, total_m3_ha=18.0)]
        result = svc._sector_analytics_from_events(
            sector_id="s1", sector_name="S01", crop_type="almond",
            events=events, period_start=date(2026, 5, 22), period_end=date(2026, 5, 28),
        )
        # 7 days: May 22 to May 28
        assert len(result.daily_m3_ha) == 7
        # Only May 22 has data
        day_22 = next(d for d in result.daily_m3_ha if d.date == date(2026, 5, 22))
        assert day_22.total_m3_ha == pytest.approx(18.0)
        zeros = [d for d in result.daily_m3_ha if d.date != date(2026, 5, 22)]
        assert all(d.total_m3_ha == 0.0 for d in zeros)

    def test_interval_stats_computed(self):
        from app.services.flowmeter_analytics import FlowmeterAnalyticsService
        svc = FlowmeterAnalyticsService()
        # Events at day 0, 2, 4 → 2-day intervals
        events = [_make_event(i * 2) for i in range(3)]
        result = svc._sector_analytics_from_events(
            sector_id="s1", sector_name="S01", crop_type="almond",
            events=events, period_start=date(2026, 5, 22), period_end=date(2026, 5, 29),
        )
        assert result.avg_interval_days is not None
        assert abs(result.avg_interval_days - 2.0) < 0.1
        assert abs(result.min_interval_days - 2.0) < 0.1
        assert abs(result.max_interval_days - 2.0) < 0.1
