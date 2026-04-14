"""Unit tests for sensor anomaly detection rules."""

from datetime import UTC, datetime, timedelta

import pytest

from app.anomaly.rules.sensor_rules import (
    Reading,
    detect_depth_inconsistency,
    detect_flatline,
    detect_impossible_jump,
    detect_impossible_value,
    detect_no_response_to_irrigation,
    detect_persistent_saturation,
    detect_sudden_drying,
    detect_suspicious_repetition,
)


def make_readings(values: list[float], start: datetime | None = None, interval_h: float = 1.0) -> list[Reading]:
    if start is None:
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
    return [
        Reading(timestamp=start + timedelta(hours=i * interval_h), vwc=v)
        for i, v in enumerate(values)
    ]


SEC = "sector-1"
PRB = "probe-1"
DEPTH = 30


class TestDetectFlatline:
    def test_flatline_6_readings_is_warning(self):
        readings = make_readings([0.25] * 6)
        result = detect_flatline(readings, SEC, PRB, DEPTH)
        assert len(result) == 1
        assert result[0].severity == "warning"
        assert result[0].anomaly_type == "flatline"

    def test_flatline_12_readings_is_critical(self):
        readings = make_readings([0.25] * 12)
        result = detect_flatline(readings, SEC, PRB, DEPTH)
        assert len(result) == 1
        assert result[0].severity == "critical"

    def test_flatline_within_tolerance(self):
        """Values within ±0.001 count as identical."""
        values = [0.250, 0.2505, 0.2498, 0.250, 0.2501, 0.2503]
        readings = make_readings(values)
        result = detect_flatline(readings, SEC, PRB, DEPTH)
        assert len(result) == 1

    def test_no_flatline_varying_data(self):
        values = [0.20, 0.21, 0.22, 0.23, 0.20, 0.19]
        readings = make_readings(values)
        result = detect_flatline(readings, SEC, PRB, DEPTH)
        assert result == []

    def test_flatline_followed_by_recovery(self):
        """6 flatline readings then values change — one warning anomaly reported."""
        values = [0.25] * 6 + [0.30, 0.28, 0.25]
        readings = make_readings(values)
        result = detect_flatline(readings, SEC, PRB, DEPTH)
        assert len(result) == 1

    def test_short_run_no_anomaly(self):
        readings = make_readings([0.25] * 5)
        result = detect_flatline(readings, SEC, PRB, DEPTH)
        assert result == []

    def test_anomaly_has_data_context(self):
        readings = make_readings([0.25] * 8)
        result = detect_flatline(readings, SEC, PRB, DEPTH)
        assert result[0].data_context["stuck_value"] == 0.25
        assert result[0].data_context["run_length"] == 8


class TestDetectImpossibleJump:
    def test_large_positive_jump(self):
        readings = make_readings([0.20, 0.40])
        result = detect_impossible_jump(readings, SEC, PRB, DEPTH)
        assert len(result) == 1
        assert result[0].anomaly_type == "impossible_jump"

    def test_large_negative_jump(self):
        readings = make_readings([0.40, 0.20])
        result = detect_impossible_jump(readings, SEC, PRB, DEPTH)
        assert len(result) == 1

    def test_normal_gradual_change(self):
        readings = make_readings([0.20, 0.22, 0.24, 0.26])
        result = detect_impossible_jump(readings, SEC, PRB, DEPTH)
        assert result == []

    def test_jump_exactly_at_threshold_no_anomaly(self):
        """Jump of exactly 0.15 m³/m³ in 1h → rate = 0.15/h (not > threshold)."""
        readings = make_readings([0.20, 0.35])
        result = detect_impossible_jump(readings, SEC, PRB, DEPTH)
        assert result == []

    def test_data_context_includes_delta(self):
        readings = make_readings([0.10, 0.40])
        result = detect_impossible_jump(readings, SEC, PRB, DEPTH)
        assert abs(result[0].data_context["delta_vwc"] - 0.30) < 0.001


class TestDetectImpossibleValue:
    def test_negative_vwc_is_critical(self):
        readings = make_readings([-0.01])
        result = detect_impossible_value(readings, SEC, PRB, DEPTH)
        assert len(result) == 1
        assert result[0].severity == "critical"
        assert result[0].anomaly_type == "impossible_value"

    def test_above_max_vwc_is_critical(self):
        readings = make_readings([0.60])
        result = detect_impossible_value(readings, SEC, PRB, DEPTH)
        assert len(result) == 1
        assert result[0].severity == "critical"

    def test_normal_vwc_no_anomaly(self):
        readings = make_readings([0.15, 0.25, 0.30, 0.28])
        result = detect_impossible_value(readings, SEC, PRB, DEPTH)
        assert result == []

    def test_multiple_impossible_values(self):
        readings = make_readings([-0.01, 0.25, 0.60, 0.25])
        result = detect_impossible_value(readings, SEC, PRB, DEPTH)
        assert len(result) == 2

    def test_boundary_zero_no_anomaly(self):
        readings = make_readings([0.0])
        result = detect_impossible_value(readings, SEC, PRB, DEPTH)
        # 0.0 == IMPOSSIBLE_LOW → NOT triggered (< 0 is the check)
        assert result == []

    def test_boundary_055_no_anomaly(self):
        readings = make_readings([0.55])
        result = detect_impossible_value(readings, SEC, PRB, DEPTH)
        # 0.55 == IMPOSSIBLE_HIGH → NOT triggered (> 0.55 is the check)
        assert result == []


class TestDetectNoResponseToIrrigation:
    def test_no_response_detected(self):
        start = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        irrig_start = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        readings = make_readings(
            [0.22, 0.22, 0.22, 0.22, 0.22, 0.22, 0.22, 0.22],
            start=start,
        )
        result = detect_no_response_to_irrigation(
            readings, irrig_start, SEC, PRB, 10
        )
        assert len(result) == 1
        assert result[0].anomaly_type == "no_response_to_irrigation"
        assert result[0].severity == "warning"

    def test_normal_response_no_anomaly(self):
        start = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)
        # Use 10:30 so the 10:00 reading is still "before" and the 11:00 reading is "after"
        irrig_start = datetime(2024, 6, 1, 10, 30, tzinfo=UTC)
        # 8:00=0.22, 9:00=0.22, 10:00=0.22 (all before 10:30)
        # 11:00=0.28, 12:00=0.27 (after — delta +0.06 > threshold 0.02)
        readings = make_readings(
            [0.22, 0.22, 0.22, 0.28, 0.27, 0.26],
            start=start,
        )
        result = detect_no_response_to_irrigation(
            readings, irrig_start, SEC, PRB, 10
        )
        assert result == []

    def test_no_readings_after_irrigation(self):
        irrig_start = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        readings = make_readings(
            [0.22, 0.22],
            start=datetime(2024, 6, 1, 8, 0, tzinfo=UTC),
        )
        result = detect_no_response_to_irrigation(
            readings, irrig_start, SEC, PRB, 10
        )
        assert result == []


class TestDetectPersistentSaturation:
    def test_72h_saturation_detected(self):
        fc = 0.30
        threshold = fc * 0.95  # 0.285
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
        readings = make_readings([0.29] * 80, start=start)  # 80h
        result = detect_persistent_saturation(readings, fc, SEC, PRB, 60)
        assert len(result) == 1
        assert result[0].anomaly_type == "persistent_saturation"
        assert result[0].severity == "warning"

    def test_short_saturation_no_anomaly(self):
        fc = 0.30
        readings = make_readings([0.29] * 40)  # 40h, threshold is 72h
        result = detect_persistent_saturation(readings, fc, SEC, PRB, 60)
        assert result == []

    def test_normal_moisture_no_anomaly(self):
        fc = 0.30
        readings = make_readings([0.20] * 100)
        result = detect_persistent_saturation(readings, fc, SEC, PRB, 60)
        assert result == []


class TestDetectSuspiciousRepetition:
    def test_repeated_pattern_detected(self):
        values = [0.25, 0.26, 0.27, 0.28, 0.25, 0.26, 0.27]
        readings = make_readings(values)
        result = detect_suspicious_repetition(readings, SEC, PRB, DEPTH)
        assert len(result) == 1
        assert result[0].anomaly_type == "suspicious_repetition"

    def test_no_repetition(self):
        values = [0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.26]
        readings = make_readings(values)
        result = detect_suspicious_repetition(readings, SEC, PRB, DEPTH)
        assert result == []


class TestDetectSuddenDrying:
    def test_sudden_drying_detected(self):
        readings = make_readings([0.28, 0.17], interval_h=1.0)  # drops 0.11 in 1h
        result = detect_sudden_drying(readings, et0_mm_day=3.0, sector_id=SEC, probe_id=PRB, depth_cm=DEPTH)
        assert len(result) == 1
        assert result[0].anomaly_type == "sudden_drying"

    def test_no_anomaly_high_et0(self):
        """If ET0 ≥ 10mm/day, sudden drying is expected — no anomaly."""
        readings = make_readings([0.28, 0.17])
        result = detect_sudden_drying(readings, et0_mm_day=12.0, sector_id=SEC, probe_id=PRB, depth_cm=DEPTH)
        assert result == []

    def test_gradual_drying_no_anomaly(self):
        readings = make_readings([0.28, 0.26, 0.24, 0.22])  # 0.02/h drop
        result = detect_sudden_drying(readings, et0_mm_day=3.0, sector_id=SEC, probe_id=PRB, depth_cm=DEPTH)
        assert result == []


class TestDetectDepthInconsistency:
    def test_shallow_wetter_than_deep_for_48h(self):
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
        # Shallow = 0.30, deep = 0.15 → delta = 0.15 > threshold
        shallow = make_readings([0.30] * 55, start=start)  # 55h
        deep = make_readings([0.15] * 55, start=start)
        result = detect_depth_inconsistency(shallow, deep, SEC, PRB)
        assert len(result) == 1
        assert result[0].anomaly_type == "depth_inconsistency"

    def test_normal_gradient_no_anomaly(self):
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
        shallow = make_readings([0.25] * 55, start=start)
        deep = make_readings([0.22] * 55, start=start)  # delta = 0.03 < threshold
        result = detect_depth_inconsistency(shallow, deep, SEC, PRB)
        assert result == []
