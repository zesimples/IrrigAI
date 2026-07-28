"""Auto-apply gate for weekly probe calibration.

Decides whether a freshly computed calibration may replace a sector's live soil
bounds without a human pressing the button. Kept pure — no DB, no I/O — so every
threshold is unit-testable without fixtures (same idiom as soil_bounds.py).

The LLM plays no part here: `CalibrationQuality` is built from deterministic
statistics, and the candidate values come from the envelope/cycle calibrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.engine.staleness import PROBE_VERY_STALE_H

if TYPE_CHECKING:  # import-light: auto_calibration pulls in SQLAlchemy
    from app.engine.auto_calibration import ProbeCalibrationResult
    from app.engine.soil_bounds import ResolvedSoilBounds

# Largest move (m³/m³) an unattended run may make to either bound once a sector
# already has a trusted probe-derived calibration. ~0.05 over a 0.8 m olive root
# zone is ~40 mm of TAW — a catastrophe bound, not a fine filter.
AUTO_APPLY_MAX_DELTA_M3M3 = 0.05

# Per-depth VWC std-dev below this reads as a stuck sensor (same floor as
# ai/probe_signal._FLATLINE_STD).
AUTO_APPLY_FLATLINE_STD_M3M3 = 0.003

REASON_APPLIED = "applied"
REASON_MANUAL_OVERRIDE = "manual_override"
REASON_PROBE_STALE = "probe_stale"
REASON_FLATLINE = "flatline"
REASON_DELTA_EXCEEDS_CAP = "delta_exceeds_cap"
REASON_NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class CalibrationQuality:
    """Deterministic trust signals for the window the candidate was measured over."""

    probe_hours_since_reading: float | None
    all_depths_flatlined: bool


@dataclass(frozen=True)
class AutoApplyDecision:
    apply: bool
    reason: str


def evaluate_auto_apply(
    candidate: ProbeCalibrationResult,
    before: ResolvedSoilBounds,
    quality: CalibrationQuality,
    *,
    bounds_from_manual_override: bool,
    bounds_from_prior_calibration: bool,
) -> AutoApplyDecision:
    """Decide whether `candidate` may replace the sector's live bounds unattended.

    First matching gate wins. Plausibility and the 48-reading floor are NOT checked
    here — compute_sector_calibration returns None rather than an implausible
    result, so a candidate reaching this function has already cleared them.

    Both flags describe the RESOLVED source of `before` (i.e. what the engine
    actually computes depletion from), not raw DB rows:

    - `bounds_from_manual_override`: `before.source == "scp_override"` — a deliberate
      human soil edit is governing the sector. `SectorCropProfile.is_customized`
      alone is NOT this: it is set on any profile edit (e.g. `mad`), while
      soil_bounds honours the override only when both scp_fc and scp_pwp are set.
    - `bounds_from_prior_calibration`: `before.source == "probe_calibrated"` — the
      live bounds are a trusted probe-derived value the cap can meaningfully guard
      movement away from. A *stale* calibration is not this: soil_bounds ignores it
      and `before` is then a preset, which the cap must never be measured against.
    """
    # 1. A deliberate human soil edit outranks measurement. Note the caller must
    #    also leave `SectorCropProfile.is_customized` untouched — unlike the manual
    #    endpoints, the scheduler never clears an agronomist's choice.
    if bounds_from_manual_override:
        return AutoApplyDecision(False, REASON_MANUAL_OVERRIDE)

    # 2. A dead probe's window may be mostly frozen or missing data. Missing
    #    last_reading_at counts as stale (same convention as is_calibration_stale).
    hours = quality.probe_hours_since_reading
    if hours is None or hours > PROBE_VERY_STALE_H:
        return AutoApplyDecision(False, REASON_PROBE_STALE)

    # 3. Every usable depth flat → stuck sensor. One flat *deep* depth is normal
    #    (no root uptake, no drainage), which is why this is all-not-any.
    if quality.all_depths_flatlined:
        return AutoApplyDecision(False, REASON_FLATLINE)

    # 4. Drift guard. Only meaningful against a previously trusted probe-derived
    #    value: when `before` is a soil-texture table lookup (never calibrated, or
    #    calibrated so long ago that the resolver ignores it), a large distance means
    #    the preset is wrong (the clamp bug), not that the measurement is anomalous.
    #    Hence a first — or post-staleness — application is uncapped.
    if bounds_from_prior_calibration:
        fc_move = abs(candidate.observed_fc - before.fc)
        refill_move = abs(candidate.observed_refill - before.pwp)
        if fc_move > AUTO_APPLY_MAX_DELTA_M3M3 or refill_move > AUTO_APPLY_MAX_DELTA_M3M3:
            return AutoApplyDecision(False, REASON_DELTA_EXCEEDS_CAP)

    return AutoApplyDecision(True, REASON_APPLIED)
