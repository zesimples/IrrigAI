import pytest

from app.engine.auto_calibration import (
    compute_envelope_points,
    is_plausible_calibration,
    percentile,
)
from app.models import ProbeCalibration


def test_probe_calibration_table_registered():
    assert ProbeCalibration.__tablename__ == "probe_calibration"
    cols = set(ProbeCalibration.__table__.columns.keys())
    assert {
        "id", "sector_id", "observed_fc", "observed_refill",
        "method", "num_cycles", "consistency", "window_days", "computed_at",
    } <= cols


def test_percentile_interpolates():
    assert percentile([0.0, 1.0], 50.0) == pytest.approx(0.5)
    assert percentile([0.0, 1.0, 2.0, 3.0, 4.0], 0.0) == 0.0
    assert percentile([0.0, 1.0, 2.0, 3.0, 4.0], 100.0) == 4.0


def test_percentile_single_value():
    assert percentile([0.42], 95.0) == 0.42


def test_envelope_points_pick_high_and_low_of_band():
    # A pinned sensor oscillating ~0.40–0.46 m³/m³.
    values = [0.40, 0.41, 0.42, 0.43, 0.44, 0.45, 0.46] * 8
    fc, refill = compute_envelope_points(values)
    assert 0.44 <= fc <= 0.46          # high percentile ~ drained upper limit
    assert 0.40 <= refill <= 0.42      # low percentile ~ operating lower bound
    assert fc > refill


def test_plausible_calibration_accepts_realistic_band():
    assert is_plausible_calibration(observed_fc=0.45, observed_refill=0.30) is True


def test_plausible_calibration_rejects_out_of_range_fc():
    assert is_plausible_calibration(observed_fc=0.05, observed_refill=0.01) is False
    assert is_plausible_calibration(observed_fc=0.75, observed_refill=0.40) is False


def test_plausible_calibration_rejects_tiny_spread():
    # FC and refill within 0.03 m³/m³ → unusable (TAW would be ~0).
    assert is_plausible_calibration(observed_fc=0.40, observed_refill=0.39) is False
