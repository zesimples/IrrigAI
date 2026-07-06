"""Pure-math tests for the irrigation fingerprint (dose-do-dia learning)."""
from datetime import UTC, datetime, timedelta

from app.engine.irrigation_fingerprint import (
    EventDose,
    compute_event_dose,
    compute_fingerprint,
    is_fingerprint_stale,
    layer_thicknesses_mm,
)

T0 = datetime(2026, 7, 1, 6, 0, tzinfo=UTC)


def _series(depth_values: dict[int, list[float]], start: datetime, step_min: int = 60):
    """Build {depth_cm: [(ts, vwc), ...]} with a fixed reading interval."""
    return {
        d: [(start + timedelta(minutes=i * step_min), v) for i, v in enumerate(vals)]
        for d, vals in depth_values.items()
    }


class TestLayerThicknesses:
    def test_midpoint_layers_10_20_30(self):
        layers = layer_thicknesses_mm([10, 20, 30])
        # 10cm sensor: surface(0) → midpoint(15) = 15 cm = 150 mm
        # 20cm sensor: 15 → 25 = 100 mm; 30cm sensor: 25 → 35 = 100 mm
        assert layers == {10: 150.0, 20: 100.0, 30: 100.0}

    def test_root_depth_caps_bottom_layer(self):
        layers = layer_thicknesses_mm([10, 20, 30], root_depth_cm=28.0)
        assert layers[30] == 30.0  # 25 → 28 = 3 cm

    def test_empty(self):
        assert layer_thicknesses_mm([]) == {}


class TestComputeEventDose:
    def test_clean_event(self):
        # Baseline 0.20, rises to 0.24 at both depths over 2h
        series = _series(
            {10: [0.20, 0.20, 0.22, 0.24, 0.24], 20: [0.20, 0.20, 0.21, 0.24, 0.24]},
            start=T0 - timedelta(hours=2),
        )
        layers = layer_thicknesses_mm([10, 20])  # {10: 150, 20: 100}
        dose = compute_event_dose(series, event_ts=T0, layers_mm=layers)
        assert dose is not None
        # delta 0.04 × 150mm + 0.04 × 100mm = 6 + 4 = 10 mm
        assert dose.net_mm == 10.0
        # peak reached 1h after event start at both depths
        assert dose.duration_min == 60.0

    def test_negligible_event_returns_none(self):
        series = _series({10: [0.200, 0.200, 0.201, 0.201, 0.201]}, start=T0 - timedelta(hours=2))
        assert compute_event_dose(series, T0, layer_thicknesses_mm([10])) is None

    def test_no_readings_after_event_returns_none(self):
        series = _series({10: [0.20, 0.20, 0.20]}, start=T0 - timedelta(hours=3))
        assert compute_event_dose(series, T0, layer_thicknesses_mm([10])) is None

    def test_falling_vwc_clamped_to_zero(self):
        series = _series(
            {10: [0.30, 0.30, 0.25, 0.24, 0.23], 20: [0.20, 0.20, 0.26, 0.26, 0.26]},
            start=T0 - timedelta(hours=2),
        )
        dose = compute_event_dose(series, T0, layer_thicknesses_mm([10, 20]))
        assert dose is not None
        assert dose.net_mm == 6.0  # only the 20cm rise counts: 0.06 × 100


class TestComputeFingerprint:
    def _dose(self, mm, dur=120.0, ts=T0):
        return EventDose(event_timestamp=ts, net_mm=mm, duration_min=dur)

    def test_fewer_than_three_events_returns_none(self):
        assert compute_fingerprint([self._dose(5), self._dose(6)]) is None

    def test_median_of_events(self):
        fp = compute_fingerprint([self._dose(4), self._dose(5), self._dose(6)])
        assert fp is not None
        assert fp.typical_event_net_mm == 5.0
        assert fp.typical_event_duration_min == 120.0
        assert fp.n_events == 3
        assert fp.confidence == "medium"
        assert fp.window_days == 25

    def test_high_confidence_needs_six_consistent_events(self):
        fp = compute_fingerprint([self._dose(5.0) for _ in range(6)])
        assert fp is not None
        assert fp.confidence == "high"
        assert fp.consistency == 1.0

    def test_duration_none_when_too_few_durations(self):
        doses = [self._dose(5, dur=None), self._dose(5, dur=None), self._dose(5, dur=90.0)]
        fp = compute_fingerprint(doses)
        assert fp is not None
        assert fp.typical_event_duration_min is None


class TestStaleness:
    def test_fresh(self):
        assert is_fingerprint_stale(T0 - timedelta(days=24), now=T0) is False

    def test_stale_at_25_days(self):
        assert is_fingerprint_stale(T0 - timedelta(days=25), now=T0) is True
