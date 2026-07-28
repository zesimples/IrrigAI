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
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is True
    assert decision.reason == REASON_APPLIED


def test_manual_override_blocks():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(fc=0.30, pwp=0.19, source="scp_override"),
        _quality(),
        bounds_from_manual_override=True,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_MANUAL_OVERRIDE


def test_manual_override_wins_over_staleness():
    """Gate precedence: an override-governed AND stale sector reports manual_override."""
    decision = evaluate_auto_apply(
        _candidate(),
        _before(source="scp_override"),
        _quality(hours=500.0),
        bounds_from_manual_override=True,
        bounds_from_prior_calibration=True,
    )
    assert decision.reason == REASON_MANUAL_OVERRIDE


def test_stale_probe_blocks():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(hours=73.0),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_PROBE_STALE


def test_missing_last_reading_treated_as_stale():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(hours=None),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.reason == REASON_PROBE_STALE


def test_fresh_boundary_at_threshold_applies():
    """72.0h is still 'fresh enough' — only strictly beyond it vetoes."""
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(hours=72.0),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is True


def test_all_depths_flatlined_blocks():
    decision = evaluate_auto_apply(
        _candidate(),
        _before(),
        _quality(flat=True),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_FLATLINE


def test_delta_cap_blocks_large_fc_move_on_calibrated_sector():
    decision = evaluate_auto_apply(
        _candidate(fc=0.42),
        _before(fc=0.29),
        _quality(),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_DELTA_EXCEEDS_CAP


def test_delta_cap_blocks_refill_only_move():
    """TAW is the spread — a steady FC with a collapsing refill must still block."""
    decision = evaluate_auto_apply(
        _candidate(fc=0.30, refill=0.11),
        _before(fc=0.30, pwp=0.19),
        _quality(),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is False
    assert decision.reason == REASON_DELTA_EXCEEDS_CAP


def test_delta_exactly_at_cap_applies():
    decision = evaluate_auto_apply(
        _candidate(fc=0.30 + AUTO_APPLY_MAX_DELTA_M3M3, refill=0.19),
        _before(fc=0.30, pwp=0.19),
        _quality(),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
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
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=False,
    )
    assert decision.apply is True
    assert decision.reason == REASON_APPLIED


def test_stale_prior_calibration_is_not_capped():
    """REGRESSION GUARD (stale-calibration deadlock).

    A sector calibrated 100 days ago has a probe_calibration row, but
    resolve_soil_bounds IGNORES a calibration past CALIB_MAX_AGE_DAYS, so `before`
    is the clamping preset (0.16) — NOT the old probe value. Keying the cap on "a
    row exists" therefore measured a 0.28 move against a preset the sector was
    never measured on and returned delta_exceeds_cap every Monday, and the
    calibration could only get staler: blocked forever. The cap must apply only
    while the live bounds ARE probe-derived, which is what
    `bounds_from_prior_calibration=False` encodes here.
    """
    decision = evaluate_auto_apply(
        _candidate(fc=0.44, refill=0.24),
        _before(fc=0.16, pwp=0.07, source="plot_preset"),
        _quality(),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=False,
    )
    assert decision.apply is True
    assert decision.reason == REASON_APPLIED


def test_customized_profile_that_does_not_govern_bounds_is_not_an_override():
    """REGRESSION GUARD (is_customized that does not affect soil bounds).

    PUT /crop-profile sets SectorCropProfile.is_customized=True on ANY edit — e.g.
    bumping `mad` — but resolve_soil_bounds honours scp_override only when BOTH
    scp_fc and scp_pwp are non-null. With soil fields NULL the sector is still
    governed by the clamping preset, so gating on the raw flag reported
    manual_override forever while the sector stayed pinned at ~0% depletion: the
    exact bug this feature exists to fix. Only a resolved source of "scp_override"
    is a real human soil decision. The service derives that from `before.source`;
    this asserts the gate itself never fires without it.
    """
    decision = evaluate_auto_apply(
        _candidate(fc=0.31, refill=0.20),
        _before(fc=0.16, pwp=0.07, source="plot_preset"),
        _quality(),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=False,
    )
    assert decision.reason != REASON_MANUAL_OVERRIDE
    assert decision.apply is True


def test_envelope_method_is_eligible():
    """Gating on method='cycles' would reject the population this feature targets."""
    decision = evaluate_auto_apply(
        _candidate(method="envelope"),
        _before(),
        _quality(),
        bounds_from_manual_override=False,
        bounds_from_prior_calibration=True,
    )
    assert decision.apply is True
