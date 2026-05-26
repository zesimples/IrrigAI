# backend/tests/test_flowmeter/test_flowmeter_checker.py
"""Tests for FlowmeterAlertChecker — outlier stripping and deviation logic.

The checker now works on 15-min FlowmeterReading rows, not IrrigationEventDetected.
Per (flowmeter, calendar-day): sort readings, strip first+last, sum interior → daily total.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from unittest.mock import MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_reading(fm_id: str, ts: datetime, value_m3_ha: float) -> MagicMock:
    """Create a mock FlowmeterReading."""
    r = MagicMock()
    r.flowmeter_id = fm_id
    r.timestamp = ts
    r.value_m3_ha = value_m3_ha
    return r


def _make_pair(fm_id: str, sector_id: str, sector_name: str, crop_type: str):
    """Create a mock (Flowmeter, Sector) pair."""
    fm = MagicMock()
    fm.id = fm_id
    sector = MagicMock()
    sector.id = sector_id
    sector.name = sector_name
    sector.crop_type = crop_type
    return (fm, sector)


def _day_readings(fm_id: str, day: date, values: list) -> list:
    """Create readings at 15-min intervals starting at 06:00 for a single day.

    With values [5.0, 15.0, 5.0]:
      06:00 → 5.0  (stripped as first)
      06:15 → 15.0 (interior)
      06:30 → 5.0  (stripped as last)
    → daily total = 15.0
    """
    base = datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)
    return [
        _make_reading(fm_id, base + timedelta(minutes=15 * i), v)
        for i, v in enumerate(values)
    ]


def _day_hourly_readings(fm_id: str, day: date, values: list) -> list:
    """Create readings at 1-hour intervals starting at 06:00 for a single day."""
    base = datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)
    return [
        _make_reading(fm_id, base + timedelta(hours=i), v)
        for i, v in enumerate(values)
    ]


BASE_DATE = date(2026, 5, 18)


def _days(n: int) -> list:
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

    def test_no_readings_yields_insufficient_data(self):
        """Farm with no readings → sector has 0 interior days → insufficient_data."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        result = self.checker._compute_from_data(pairs, [])
        assert result.sector_results[0].interior_avg is None
        assert result.crop_averages == {}

    def test_single_reading_per_day_classified_hourly(self):
        """Flowmeter with 1 reading/day: 24-hour gaps → classified as hourly → readings count.

        A flowmeter that only fires once daily has a ~1440-min median interval, which
        exceeds HOURLY_THRESHOLD_MINUTES, so no stripping is applied and the single
        reading per day contributes to the daily total.
        """
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [15.0])   # 1 reading/day → 24h interval
        result = self.checker._compute_from_data(pairs, readings)
        # Classified as hourly → reading counts → avg = 15.0, not None
        assert result.sector_results[0].interior_avg == pytest.approx(15.0)

    def test_subhourly_sparse_day_excluded(self):
        """Sub-hourly flowmeter: a day with < 3 readings is skipped (cannot form interior).

        Days 0-1 have 3 readings each (→ establishes 15-min interval, 2 interior days = MIN).
        Day 2 has only 1 reading → skipped. interior_days has 2 entries, not 3.
        """
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(2):
            readings += _day_readings("fm1", d, [5.0, 15.0, 5.0])
        sparse_day = BASE_DATE + timedelta(days=2)
        readings += _day_readings("fm1", sparse_day, [15.0])   # sparse day, skipped
        result = self.checker._compute_from_data(pairs, readings)
        assert len(result.sector_results[0].interior_days) == 2

    def test_two_readings_per_day_excluded_for_subhourly(self):
        """Sub-hourly flowmeter: days with exactly 2 readings yield no interior.

        2 readings/day at 15-min intervals → median gap is 15 min → sub-hourly.
        But each day has only 2 readings → no interior strip is possible → all days skipped.
        """
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [10.0, 10.0])
        result = self.checker._compute_from_data(pairs, readings)
        assert result.sector_results[0].interior_avg is None

    def test_first_last_stripped_per_day(self):
        """Day with 3 readings → only middle reading is interior; outlier values ignored."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [5.0, 15.0, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
        assert result.sector_results[0].interior_avg == pytest.approx(15.0)

    def test_multiple_interior_readings_summed(self):
        """Day with 5 readings → 3 interior readings summed as day total."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(4):
            # strip 2.0 (first) and 2.0 (last); interior = [10.0, 10.0, 10.0] → sum = 30.0
            readings += _day_readings("fm1", d, [2.0, 10.0, 10.0, 10.0, 2.0])
        result = self.checker._compute_from_data(pairs, readings)
        assert result.sector_results[0].interior_avg == pytest.approx(30.0)

    def test_deviation_above_threshold_fires_alert(self):
        """Sector A daily total 18, sector B daily total 14 → crop avg 16 → A is +12.5%."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [5.0, 18.0, 5.0])
            readings += _day_readings("fm2", d, [5.0, 14.0, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        sector_a = next(a for a in deviation_alerts if a.sector_id == "s1")
        assert sector_a.data["direction"] == "above"
        assert sector_a.data["deviation_pct"] == pytest.approx(12.5)

    def test_deviation_below_threshold_fires_alert(self):
        """Sector B daily total 14 → −12.5% below crop avg 16 → alert direction=below."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [5.0, 18.0, 5.0])
            readings += _day_readings("fm2", d, [5.0, 14.0, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        sector_b = next(a for a in deviation_alerts if a.sector_id == "s2")
        assert sector_b.data["direction"] == "below"
        assert sector_b.data["deviation_pct"] == pytest.approx(-12.5)

    def test_within_threshold_no_deviation_alert(self):
        """Sectors at ±3.1% → under threshold → no FLOWMETER_DEVIATION."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [5.0, 16.5, 5.0])
            readings += _day_readings("fm2", d, [5.0, 15.5, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        assert len(deviation_alerts) == 0

    def test_insufficient_data_alert_fired(self):
        """Sector with only 1 interior day (< MIN=2) → FLOWMETER_INSUFFICIENT_DATA."""
        from app.core.enums import AlertType
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(1):   # only 1 day → below MIN_INTERIOR_DAYS=2
            readings += _day_readings("fm1", d, [5.0, 15.0, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
        alerts = self.checker._build_alerts(result, "farm1")
        insuf = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_INSUFFICIENT_DATA]
        assert len(insuf) == 1
        assert insuf[0].data["interior_day_count"] == 1

    def test_hourly_flowmeter_no_stripping(self):
        """Hourly flowmeter: all readings count, first+last NOT stripped.

        Values [5.0, 15.0, 5.0] at 1-h intervals → day total = 25.0
        (sub-hourly would strip to 15.0).
        """
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(4):
            readings += _day_hourly_readings("fm1", d, [5.0, 15.0, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
        assert result.sector_results[0].interior_avg == pytest.approx(25.0)

    def test_hourly_single_reading_per_day_counts(self):
        """Hourly flowmeter with 1 reading/day: still contributes (no ≥3 requirement)."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(4):
            readings += _day_hourly_readings("fm1", d, [12.0])
        result = self.checker._compute_from_data(pairs, readings)
        assert result.sector_results[0].interior_avg == pytest.approx(12.0)

    def test_mixed_intervals_independent_treatment(self):
        """Farm with one hourly and one 15-min sector: each handled correctly.

        Hourly sector: [5.0, 15.0, 5.0] → daily total 25.0
        15-min sector: [5.0, 15.0, 5.0] → daily total 15.0 (first+last stripped)
        crop avg = mean(25.0, 15.0) = 20.0 → both deviate.
        """
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor Hourly", "almond"),
            _make_pair("fm2", "s2", "Setor Fast",   "almond"),
        ]
        readings = []
        for d in _days(4):
            readings += _day_hourly_readings("fm1", d, [5.0, 15.0, 5.0])   # hourly → 25.0/day
            readings += _day_readings("fm2", d, [5.0, 15.0, 5.0])          # 15-min → 15.0/day
        result = self.checker._compute_from_data(pairs, readings)
        assert result.sector_results[0].interior_avg == pytest.approx(25.0)
        assert result.sector_results[1].interior_avg == pytest.approx(15.0)
        assert result.crop_averages["almond"] == pytest.approx(20.0)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        assert len(deviation_alerts) == 2

    def test_single_sector_per_crop_no_deviation(self):
        """Only one almond sector → crop_avg == sector_avg → deviation is 0 → no alert."""
        from app.core.enums import AlertType
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [5.0, 20.0, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
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
        readings = []
        for d in _days(4):
            readings += _day_readings("fm1", d, [5.0, 20.0, 5.0])
            readings += _day_readings("fm2", d, [5.0, 16.0, 5.0])
            readings += _day_readings("fm3", d, [5.0, 10.0, 5.0])
        result = self.checker._compute_from_data(pairs, readings)
        assert result.crop_averages["almond"] == pytest.approx(18.0)
        assert result.crop_averages["olive"] == pytest.approx(10.0)
        alerts = self.checker._build_alerts(result, "farm1")
        olive_deviations = [
            a for a in alerts
            if a.alert_type == AlertType.FLOWMETER_DEVIATION and a.sector_id == "s3"
        ]
        assert len(olive_deviations) == 0
