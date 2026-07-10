"""Regression tests for irrigation-dose deviations.

The Conqueiros meters report irrigation in interval buckets and events can cross
midnight. The checker must therefore use detected event totals, not UTC calendar
days or trimmed raw readings.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

BASE_TIME = datetime(2026, 5, 18, 22, 0, tzinfo=UTC)


def _make_pair(fm_id: str, sector_id: str, sector_name: str, crop_type: str):
    flowmeter = MagicMock()
    flowmeter.id = fm_id
    sector = MagicMock()
    sector.id = sector_id
    sector.name = sector_name
    sector.crop_type = crop_type
    return flowmeter, sector


def _make_event(
    flowmeter_id: str,
    day_offset: int,
    total_m3_ha: float,
    *,
    crosses_midnight: bool = False,
) -> MagicMock:
    event = MagicMock()
    event.flowmeter_id = flowmeter_id
    event.total_m3_ha = total_m3_ha
    event.start_time = BASE_TIME + timedelta(days=day_offset)
    event.end_time = event.start_time + timedelta(hours=3 if crosses_midnight else 1)
    return event


def _events(flowmeter_id: str, values: list[float]) -> list[MagicMock]:
    return [_make_event(flowmeter_id, index * 2, value) for index, value in enumerate(values)]


def _evaluations_by_sector(checker, result):
    return {
        evaluation.sector.sector_id: evaluation for evaluation in checker._evaluate_sectors(result)
    }


def test_flowmeter_deviations_response_schema_constructs():
    from app.schemas.flowmeter import FlowmeterDeviationsResponse

    response = FlowmeterDeviationsResponse(
        period_days=7,
        sectors=[],
        deviating=[],
        insufficient_data=[],
        crop_averages={},
        evaluated_at=datetime.now(UTC),
    )
    assert response.period_days == 7
    assert response.sectors == []


class TestFlowmeterAlertChecker:
    def setup_method(self):
        from app.alerts.flowmeter_checker import FlowmeterAlertChecker

        self.checker = FlowmeterAlertChecker()

    def test_no_events_is_insufficient_data(self):
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]

        result = self.checker._compute_from_events(pairs, [])
        evaluation = _evaluations_by_sector(self.checker, result)["s1"]

        assert evaluation.status == "insufficient_data"
        assert evaluation.peer_sector_count == 0

    def test_one_event_is_insufficient_data(self):
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]

        result = self.checker._compute_from_events(
            pairs,
            [_make_event("fm1", 0, 12.0)],
        )

        assert result.sector_results[0].typical_dose is None

    def test_typical_dose_is_event_median(self):
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]

        result = self.checker._compute_from_events(pairs, _events("fm1", [8.0, 10.0, 50.0]))

        assert result.sector_results[0].typical_dose == pytest.approx(10.0)

    def test_event_crossing_midnight_is_not_split(self):
        """A night irrigation remains one event even though it spans two UTC dates."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = [
            _make_event("fm1", 0, 12.0, crosses_midnight=True),
            _make_event("fm1", 2, 14.0, crosses_midnight=True),
        ]

        result = self.checker._compute_from_events(pairs, events)

        assert result.sector_results[0].event_doses == [12.0, 14.0]
        assert result.sector_results[0].typical_dose == pytest.approx(13.0)

    def test_single_sector_crop_has_insufficient_peer_data(self):
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]

        result = self.checker._compute_from_events(pairs, _events("fm1", [10.0, 10.0]))
        evaluation = _evaluations_by_sector(self.checker, result)["s1"]

        assert evaluation.status == "insufficient_peer_data"
        assert evaluation.peer_sector_count == 0

    def test_requires_two_same_crop_peers(self):
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        events = _events("fm1", [10.0, 10.0]) + _events("fm2", [12.0, 12.0])

        result = self.checker._compute_from_events(pairs, events)
        evaluations = _evaluations_by_sector(self.checker, result)

        assert evaluations["s1"].status == "insufficient_peer_data"
        assert evaluations["s2"].status == "insufficient_peer_data"

    def test_leave_one_out_median_excludes_sector_under_test(self):
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
            _make_pair("fm3", "s3", "Setor C", "almond"),
            _make_pair("fm4", "s4", "Setor D", "almond"),
        ]
        events = (
            _events("fm1", [10.0, 10.0])
            + _events("fm2", [10.0, 10.0])
            + _events("fm3", [10.0, 10.0])
            + _events("fm4", [20.0, 20.0])
        )

        result = self.checker._compute_from_events(pairs, events)
        evaluation = _evaluations_by_sector(self.checker, result)["s4"]

        assert evaluation.crop_baseline == pytest.approx(10.0)
        assert evaluation.deviation_pct == pytest.approx(100.0)
        assert evaluation.status == "warning"

    def test_median_baseline_is_robust_to_an_outlier(self):
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
            _make_pair("fm3", "s3", "Setor C", "almond"),
            _make_pair("fm4", "s4", "Setor D", "almond"),
        ]
        events = (
            _events("fm1", [10.0, 10.0])
            + _events("fm2", [10.0, 10.0])
            + _events("fm3", [10.0, 10.0])
            + _events("fm4", [100.0, 100.0])
        )

        result = self.checker._compute_from_events(pairs, events)
        evaluation = _evaluations_by_sector(self.checker, result)["s4"]

        assert evaluation.crop_baseline == pytest.approx(10.0)
        assert evaluation.deviation_pct == pytest.approx(900.0)

    @pytest.mark.parametrize(
        ("dose", "expected_status"),
        [(11.0, "info"), (12.0, "warning")],
    )
    def test_severity_bands(self, dose, expected_status):
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
            _make_pair("fm3", "s3", "Setor C", "almond"),
            _make_pair("fm4", "s4", "Setor D", "almond"),
        ]
        events = (
            _events("fm1", [10.0, 10.0])
            + _events("fm2", [10.0, 10.0])
            + _events("fm3", [10.0, 10.0])
            + _events("fm4", [dose, dose])
        )

        result = self.checker._compute_from_events(pairs, events)

        assert _evaluations_by_sector(self.checker, result)["s4"].status == expected_status

    def test_crop_baselines_are_isolated(self):
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
            _make_pair("fm3", "s3", "Setor C", "almond"),
            _make_pair("fm4", "s4", "Setor D", "olive"),
        ]
        events = (
            _events("fm1", [10.0, 10.0])
            + _events("fm2", [10.0, 10.0])
            + _events("fm3", [10.0, 10.0])
            + _events("fm4", [30.0, 30.0])
        )

        result = self.checker._compute_from_events(pairs, events)
        evaluations = _evaluations_by_sector(self.checker, result)

        assert result.crop_averages["almond"] == pytest.approx(10.0)
        assert result.crop_averages["olive"] == pytest.approx(30.0)
        assert evaluations["s4"].status == "insufficient_peer_data"

    def test_conqueiros_night_irrigation_pattern_keeps_normal_sectors_normal(self):
        """Comparable night irrigations must not become deviations at midnight."""
        pairs = [
            _make_pair("fm1", "s1", "A1", "almond"),
            _make_pair("fm2", "s2", "A2", "almond"),
            _make_pair("fm3", "s3", "A3", "almond"),
            _make_pair("fm4", "s4", "A4", "almond"),
        ]
        events = []
        for flowmeter_id, dose in (("fm1", 16.0), ("fm2", 16.2), ("fm3", 15.9), ("fm4", 16.1)):
            events.extend(
                [
                    _make_event(flowmeter_id, 0, dose, crosses_midnight=True),
                    _make_event(flowmeter_id, 3, dose, crosses_midnight=True),
                ]
            )

        result = self.checker._compute_from_events(pairs, events, period_days=7)
        evaluations = _evaluations_by_sector(self.checker, result)

        assert result.period_days == 7
        assert {evaluation.status for evaluation in evaluations.values()} == {"normal"}

    def test_alerts_use_info_and_warning_severity(self):
        from app.core.enums import AlertSeverity, AlertType

        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
            _make_pair("fm3", "s3", "Setor C", "almond"),
            _make_pair("fm4", "s4", "Setor D", "almond"),
            _make_pair("fm5", "s5", "Setor E", "almond"),
        ]
        events = (
            _events("fm1", [10.0, 10.0])
            + _events("fm2", [10.0, 10.0])
            + _events("fm3", [10.0, 10.0])
            + _events("fm4", [11.0, 11.0])
            + _events("fm5", [12.0, 12.0])
        )

        alerts = self.checker._build_alerts(
            self.checker._compute_from_events(pairs, events),
            "farm1",
        )
        deviations = [
            alert for alert in alerts if alert.alert_type == AlertType.FLOWMETER_DEVIATION
        ]
        severity_by_sector = {alert.sector_id: alert.severity for alert in deviations}

        assert severity_by_sector["s4"] == AlertSeverity.INFO
        assert severity_by_sector["s5"] == AlertSeverity.WARNING
