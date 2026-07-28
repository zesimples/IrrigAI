"""Pure unit tests for the auto-apply gate. No DB, no fixtures."""

from app.engine.auto_calibration import ProbeCalibrationResult
from app.engine.calibration_policy import (
    AUTO_APPLY_MAX_DELTA_M3M3,
    REASON_APPLIED,
    REASON_DELTA_EXCEEDS_CAP,
    REASON_FLATLINE,
    REASON_MANUAL_OVERRIDE,
    REASON_PROBE_STALE,
    CalibrationQuality,
    evaluate_auto_apply,
)
from app.engine.soil_bounds import ResolvedSoilBounds


def _candidate(fc: float = 0.31, refill: float = 0.20, method: str = "cycles"):
    return ProbeCalibrationResult(
        observed_fc=fc,
        observed_refill=refill,
        method=method,
        num_cycles=4,
        consistency=0.8,
        window_days=30,
    )


def _before(fc: float = 0.30, pwp: float = 0.19, source: str = "probe_calibrated"):
    return ResolvedSoilBounds(fc=fc, pwp=pwp, source=source, calibration=None)


def _quality(hours: float | None = 5.0, flat: bool = False):
    return CalibrationQuality(probe_hours_since_reading=hours, all_depths_flatlined=flat)


def test_healthy_candidate_applies():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is True
    assert decision.reason == REASON_APPLIED


def test_manual_override_blocks():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(fc=0.30, pwp=0.19, source="scp_override"),
        _quality(),
        is_customized=True,
        has_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_MANUAL_OVERRIDE


def test_manual_override_wins_over_staleness():
    """Gate precedence: a customized AND stale sector reports manual_override."""
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(hours=500.0),
        is_customized=True,
        has_prior_calibration=True,
    )
    assert decision.reason == REASON_MANUAL_OVERRIDE


def test_stale_probe_blocks():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(hours=73.0),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_PROBE_STALE


def test_missing_last_reading_treated_as_stale():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(hours=None),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.reason == REASON_PROBE_STALE


def test_fresh_boundary_at_threshold_applies():
    """72.0h is still 'fresh enough' — only strictly beyond it vetoes."""
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(hours=72.0),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is True


def test_all_depths_flatlined_blocks():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(flat=True),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_FLATLINE


def test_delta_cap_blocks_large_fc_move_on_calibrated_sector():
    decision = evaluate_auto_apply(
        _candidate(fc=0.42),
        _before(fc=0.29),
        _quality(),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_DELTA_EXCEEDS_CAP


def test_delta_cap_blocks_refill_only_move():
    """TAW is the spread — a steady FC with a collapsing refill must still block."""
    decision = evaluate_auto_apply(
        _candidate(fc=0.30, refill=0.11),
        _before(fc=0.30, pwp=0.19),
        _quality(),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_DELTA_EXCEEDS_CAP


def test_delta_exactly_at_cap_applies():
    decision = evaluate_auto_apply(
        _candidate(fc=0.30 + AUTO_APPLY_MAX_DELTA_M3M3, refill=0.19),
        _before(fc=0.30, pwp=0.19),
        _quality(),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is True


def test_first_ever_application_is_uncapped():
    """A never-calibrated clamped sector: preset 0.16 -> measured 0.31 must apply.

    Distance from an unmeasured soil-texture preset is not evidence of anomaly —
    it is the clamp bug this feature exists to fix.
    """
    decision = evaluate_auto_apply(
        _candidate(fc=0.31, refill=0.20),
        _before(fc=0.16, pwp=0.07, source="plot_preset"),
        _quality(),
        is_customized=False,
        has_prior_calibration=False,
    )
    assert decision.apply is True
    assert decision.reason == REASON_APPLIED


def test_envelope_method_is_eligible():
    """Gating on method='cycles' would reject the population this feature targets."""
    decision = evaluate_auto_apply(
        _candidate(method="envelope"),
        _before(),
        _quality(),
        is_customized=False,
        has_prior_calibration=True,
    )
    assert decision.apply is True
