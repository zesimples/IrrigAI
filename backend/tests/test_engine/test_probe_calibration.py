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


def test_scp_override_wins():
    from app.engine.soil_bounds import resolve_soil_bounds

    b = resolve_soil_bounds(
        scp_fc=0.30, scp_pwp=0.15,
        calib_fc=0.45, calib_refill=0.30, calib_meta={"method": "cycles"},
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.30, 0.15, "scp")
    assert b.calibration is None


def test_calibration_wins_over_plot_preset():
    from app.engine.soil_bounds import resolve_soil_bounds

    meta = {"method": "envelope", "observed_fc": 0.45}
    b = resolve_soil_bounds(
        scp_fc=None, scp_pwp=None,
        calib_fc=0.45, calib_refill=0.30, calib_meta=meta,
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.45, 0.30, "probe_calibrated")
    assert b.calibration == meta


def test_plot_preset_used_when_no_calibration():
    from app.engine.soil_bounds import resolve_soil_bounds

    b = resolve_soil_bounds(
        scp_fc=None, scp_pwp=None,
        calib_fc=None, calib_refill=None, calib_meta=None,
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.16, 0.07, "plot_preset")


def test_default_when_nothing_configured():
    from app.engine.soil_bounds import DEFAULT_FC, DEFAULT_PWP, resolve_soil_bounds

    b = resolve_soil_bounds(
        scp_fc=None, scp_pwp=None,
        calib_fc=None, calib_refill=None, calib_meta=None,
        plot_fc=None, plot_pwp=None,
    )
    assert (b.fc, b.pwp, b.source) == (DEFAULT_FC, DEFAULT_PWP, "default")
