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


# ── FlowmeterAlertChecker unit tests (no DB) ─────────────────────────────────

class TestFlowmeterAlertChecker:
    def setup_method(self):
        from app.alerts.flowmeter_checker import FlowmeterAlertChecker
        self.checker = FlowmeterAlertChecker()

    def test_no_events_yields_insufficient_data(self):
        """Farm with no events → sector has 0 interior events → insufficient_data."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        result = self.checker._compute_from_data(pairs, [])
        assert result.sector_results[0].interior_avg is None
        assert result.crop_averages == {}

    def test_single_event_per_day_excluded(self):
        """Day with 1 event per sector → stripped entirely → insufficient_data."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [15.0])   # 1 event per day
        result = self.checker._compute_from_data(pairs, events)
        assert result.sector_results[0].interior_avg is None

    def test_first_last_stripped_per_day(self):
        """Day with 3 events → only middle event is interior; outlier values ignored."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 15.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        assert result.sector_results[0].interior_avg == pytest.approx(15.0)

    def test_deviation_above_threshold_fires_alert(self):
        """Sector A at 18 m³/ha, sector B at 14 m³/ha → crop avg 16 → A is +12.5%."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 18.0, 5.0])
            events += _day_events("fm2", d, [5.0, 14.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        sector_a = next(a for a in deviation_alerts if a.sector_id == "s1")
        assert sector_a.data["direction"] == "above"
        assert sector_a.data["deviation_pct"] == pytest.approx(12.5)

    def test_deviation_below_threshold_fires_alert(self):
        """Sector B at 14 m³/ha → −12.5% below crop avg 16 → alert direction=below."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 18.0, 5.0])
            events += _day_events("fm2", d, [5.0, 14.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        sector_b = next(a for a in deviation_alerts if a.sector_id == "s2")
        assert sector_b.data["direction"] == "below"
        assert sector_b.data["deviation_pct"] == pytest.approx(-12.5)

    def test_within_threshold_no_deviation_alert(self):
        """Sector at ±3.1% → under threshold → no FLOWMETER_DEVIATION."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 16.5, 5.0])
            events += _day_events("fm2", d, [5.0, 15.5, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        assert len(deviation_alerts) == 0

    def test_insufficient_data_alert_fired(self):
        """Sector with only 2 interior events (< MIN=3) → FLOWMETER_INSUFFICIENT_DATA."""
        from app.core.enums import AlertType
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(2):
            events += _day_events("fm1", d, [5.0, 15.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        insuf = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_INSUFFICIENT_DATA]
        assert len(insuf) == 1
        assert insuf[0].data["interior_event_count"] == 2

    def test_single_sector_per_crop_no_deviation(self):
        """Only one almond sector → crop_avg == sector_avg → deviation is 0 → no alert."""
        from app.core.enums import AlertType
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 20.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        assert len(deviation_alerts) == 0

    def test_crop_isolation(self):
        """Almond and olive averages computed independently; olive (1 sector) never deviates."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
            _make_pair("fm3", "s3", "Setor C", "olive"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 20.0, 5.0])
            events += _day_events("fm2", d, [5.0, 16.0, 5.0])
            events += _day_events("fm3", d, [5.0, 10.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        assert result.crop_averages["almond"] == pytest.approx(18.0)
        assert result.crop_averages["olive"] == pytest.approx(10.0)
        alerts = self.checker._build_alerts(result, "farm1")
        olive_deviations = [
            a for a in alerts
            if a.alert_type == AlertType.FLOWMETER_DEVIATION and a.sector_id == "s3"
        ]
        assert len(olive_deviations) == 0
