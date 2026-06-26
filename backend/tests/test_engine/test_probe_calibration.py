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


def test_is_calibration_stale_thresholds():
    from datetime import UTC, datetime, timedelta

    from app.engine.auto_calibration import CALIB_MAX_AGE_DAYS, is_calibration_stale

    now = datetime(2026, 6, 26, tzinfo=UTC)
    fresh = now - timedelta(days=CALIB_MAX_AGE_DAYS - 1)
    stale = now - timedelta(days=CALIB_MAX_AGE_DAYS + 1)
    assert is_calibration_stale(fresh, now=now) is False
    assert is_calibration_stale(stale, now=now) is True
    # Missing computed_at is treated as stale.
    assert is_calibration_stale(None, now=now) is True
    # Naive datetime assumed UTC — no crash, correct verdict.
    assert is_calibration_stale(stale.replace(tzinfo=None), now=now) is True


def test_calibration_outranks_preset_scp():
    # An auto-populated (non-customized) SCP FC must NOT beat calibration.
    from app.engine.soil_bounds import resolve_soil_bounds

    b = resolve_soil_bounds(
        scp_fc=0.30, scp_pwp=0.15, scp_customized=False,
        calib_fc=0.45, calib_refill=0.30, calib_meta={"method": "cycles"},
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.45, 0.30, "probe_calibrated")
    assert b.calibration == {"method": "cycles"}


def test_customized_scp_overrides_calibration():
    # A deliberate user soil setting (is_customized=True) wins over calibration.
    from app.engine.soil_bounds import resolve_soil_bounds

    b = resolve_soil_bounds(
        scp_fc=0.30, scp_pwp=0.15, scp_customized=True,
        calib_fc=0.45, calib_refill=0.30, calib_meta={"method": "cycles"},
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.30, 0.15, "scp_override")
    assert b.calibration is None


def test_stale_calibration_is_ignored_and_falls_through():
    # A stale calibration must NOT set the bounds; resolution falls to the next
    # source (SCP here), but the stale meta is surfaced for provenance (used=False).
    from app.engine.soil_bounds import resolve_soil_bounds

    meta = {"method": "envelope", "used": False, "stale": True}
    b = resolve_soil_bounds(
        scp_fc=0.30, scp_pwp=0.15, scp_customized=False,
        calib_fc=0.45, calib_refill=0.30, calib_meta=meta, calib_stale=True,
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.30, 0.15, "scp")
    # Provenance preserved so the API/UI can explain the calibration was ignored.
    assert b.calibration == meta


def test_stale_calibration_falls_through_to_plot_then_default():
    from app.engine.soil_bounds import DEFAULT_FC, DEFAULT_PWP, resolve_soil_bounds

    meta = {"method": "cycles", "used": False, "stale": True}
    b = resolve_soil_bounds(
        scp_fc=None, scp_pwp=None,
        calib_fc=0.45, calib_refill=0.30, calib_meta=meta, calib_stale=True,
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.16, 0.07, "plot_preset")
    assert b.calibration == meta

    b2 = resolve_soil_bounds(
        scp_fc=None, scp_pwp=None,
        calib_fc=0.45, calib_refill=0.30, calib_meta=meta, calib_stale=True,
        plot_fc=None, plot_pwp=None,
    )
    assert (b2.fc, b2.pwp, b2.source) == (DEFAULT_FC, DEFAULT_PWP, "default")
    assert b2.calibration == meta


def test_customized_scp_ignores_stale_calibration_meta():
    # Deliberate user override wins and does not surface calibration provenance.
    from app.engine.soil_bounds import resolve_soil_bounds

    b = resolve_soil_bounds(
        scp_fc=0.32, scp_pwp=0.14, scp_customized=True,
        calib_fc=0.45, calib_refill=0.30,
        calib_meta={"method": "cycles", "used": False, "stale": True}, calib_stale=True,
        plot_fc=0.16, plot_pwp=0.07,
    )
    assert (b.fc, b.pwp, b.source) == (0.32, 0.14, "scp_override")
    assert b.calibration is None


def test_scp_used_when_no_calibration():
    from app.engine.soil_bounds import resolve_soil_bounds

    b = resolve_soil_bounds(
        scp_fc=0.30, scp_pwp=0.15,
        calib_fc=None, calib_refill=None, calib_meta=None,
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


def _wb_ctx(field_capacity, wilting_point, root_depth_m=0.6, mad=0.6):
    # build_water_balance reads only these four attributes off ctx.
    from types import SimpleNamespace

    return SimpleNamespace(
        field_capacity=field_capacity,
        wilting_point=wilting_point,
        root_depth_m=root_depth_m,
        mad=mad,
    )


def test_preset_fc_pins_probe_sector_at_zero_depletion():
    from app.engine.water_balance import build_water_balance

    # T63-like: VWC sensor reads 0.44 m³/m³, preset FC is 0.16 → clamp pins depletion at 0.
    wb = build_water_balance(_wb_ctx(field_capacity=0.16, wilting_point=0.07), swc_probe=0.44)
    assert wb.depletion_mm == 0.0          # "100% da água disponível" forever


def test_calibrated_fc_unpins_probe_sector():
    from app.engine.water_balance import build_water_balance, compute_taw

    # Same probe, calibrated bounds FC=0.46 / refill=0.30 → real deficit appears.
    wb = build_water_balance(_wb_ctx(field_capacity=0.46, wilting_point=0.30), swc_probe=0.40)
    assert wb.depletion_mm > 0.0
    # Refill line as the lower bound keeps TAW in the real operating band, not ballooned.
    ballooned = compute_taw(0.46, 0.07, 0.6)
    assert wb.taw_mm < ballooned
