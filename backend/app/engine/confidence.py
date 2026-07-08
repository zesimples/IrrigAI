"""Confidence scoring.

Penalties from 00-project-brief.md, plus user-configuration completeness penalties.
Accepts both legacy string anomaly lists and typed Anomaly objects from the detector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.engine.staleness import PROBE_STALE_H, PROBE_VERY_STALE_H
from app.engine.types import (
    ConfidenceResult,
    DepthStatus,
    ProbeSnapshot,
    RootzoneStatus,
    SectorContext,
    WeatherContext,
)

if TYPE_CHECKING:
    from app.anomaly.types import Anomaly as AnomalyObj

WEATHER_STALE_H = 24.0

# Anomaly severity penalties
_ANOMALY_CRITICAL_PENALTY = 0.20
_ANOMALY_WARNING_PENALTY = 0.10


def score(
    ctx: SectorContext,
    probes: ProbeSnapshot,
    weather: WeatherContext,
    anomalies: list[str] | list[AnomalyObj] | None = None,
    swc_model_confidence: float | None = None,
) -> ConfidenceResult:
    """Compute confidence score for a recommendation.

    Returns a ConfidenceResult with score, level, per-penalty breakdown, and warnings.
    """
    conf = 1.0
    penalties: list[tuple[str, float]] = []
    warnings: list[str] = []

    # --- Probe data quality ---
    rz = probes.rootzone
    depth_statuses = getattr(rz, "depth_statuses", None)
    has_depth_quality = isinstance(depth_statuses, list) and len(depth_statuses) > 0
    if not rz.has_data:
        if swc_model_confidence is not None:
            # Defensive clamp: a public param must not produce a negative penalty
            # (which would *raise* confidence) or bypass the no-probe penalty entirely.
            swc_model_confidence = max(0.0, min(1.0, swc_model_confidence))
            pen = round(0.25 * (1.0 - swc_model_confidence), 3)
            _pen(conf, penalties, warnings,
                 f"SWC from water-balance model (conf {swc_model_confidence:.2f})", pen)
            conf -= pen
        else:
            _pen(conf, penalties, warnings, "No probe data", 0.25)
            conf -= 0.25
    elif has_depth_quality:
        conf -= _apply_depth_quality_penalties(rz, penalties, warnings)
    elif rz.hours_since_any_reading is not None and rz.hours_since_any_reading > PROBE_STALE_H:
        _pen(conf, penalties, warnings, f"Probe data stale ({rz.hours_since_any_reading:.1f}h)", 0.25)
        conf -= 0.25

    if not probes.is_calibrated:
        _pen(conf, penalties, warnings, "Probes uncalibrated", 0.10)
        conf -= 0.10

    # --- Weather data ---
    if weather.hours_since_observation is not None and weather.hours_since_observation > WEATHER_STALE_H:
        _pen(conf, penalties, warnings, f"Weather data stale ({weather.hours_since_observation:.1f}h)", 0.15)
        conf -= 0.15

    # --- Irrigation system not configured ---
    if ctx.application_rate_mm_h is None and ctx.emitter_flow_lph is None:
        _pen(conf, penalties, warnings, "Irrigation system not configured", 0.10)
        conf -= 0.10

    # --- Phenological stage not set ---
    if ctx.phenological_stage is None:
        _pen(conf, penalties, warnings, "Phenological stage not set", 0.10)
        conf -= 0.10

    # --- Anomaly detected ---
    # Accepts either legacy list[str] (from probe_interpreter) or list[Anomaly] (from detector)
    if anomalies:
        has_critical = _has_severity(anomalies, "critical")
        has_warning = _has_severity(anomalies, "warning")

        if has_critical:
            _pen(conf, penalties, warnings,
                 f"Critical anomalies detected ({_count_severity(anomalies, 'critical')})",
                 _ANOMALY_CRITICAL_PENALTY)
            conf -= _ANOMALY_CRITICAL_PENALTY
        elif has_warning:
            _pen(conf, penalties, warnings,
                 f"Warning anomalies detected ({_count_severity(anomalies, 'warning')})",
                 _ANOMALY_WARNING_PENALTY)
            conf -= _ANOMALY_WARNING_PENALTY
        else:
            # Legacy strings or info-only
            _pen(conf, penalties, warnings, f"Anomalies detected ({len(anomalies)})", 0.05)
            conf -= 0.05

    # --- No irrigation logs ---
    # (would be checked from RecentIrrigationContext — placeholder penalty here)
    # conf -= 0.05

    # --- Soil from preset (not measured) ---
    if ctx.soil_texture is not None and ctx.field_capacity is not None:
        # Has soil data — check if it's from a preset (less accurate than measured)
        # For MVP we always use preset, so apply a small penalty always
        _pen(conf, penalties, warnings, "Soil parameters from preset (not measured)", 0.05)
        conf -= 0.05
    else:
        # No soil configured at all — bigger penalty (using hard defaults)
        _pen(conf, penalties, warnings, "Soil not configured (using generic defaults)", 0.10)
        conf -= 0.10

    # --- User-configuration completeness penalties ---
    # Defaults used (user hasn't configured something → engine fell back)
    defaults_penalty = min(0.15, len(ctx.defaults_used) * 0.05)
    if ctx.defaults_used:
        _pen(conf, penalties, warnings, f"{len(ctx.defaults_used)} agronomic default(s) applied", defaults_penalty)
        conf -= defaults_penalty

    # Missing config (user hasn't set something up)
    missing_penalty = min(0.20, len(ctx.missing_config) * 0.10)
    if ctx.missing_config:
        _pen(conf, penalties, warnings, f"{len(ctx.missing_config)} config item(s) missing", missing_penalty)
        conf -= missing_penalty

    conf = round(max(0.10, conf), 3)

    # "low" is reserved exclusively for sectors with no probe readings at all.
    # Every other combination of penalties stays within medium/high so the farmer
    # is not alarmed by configuration gaps they may not control.
    if not rz.has_data:
        level = "low"
    elif conf >= 0.75:
        level = "high"
    else:
        level = "medium"

    # Structured data-source label for AI explanations and UI badges
    if not rz.has_data:
        src_conf = "no_probe"
    elif rz.hours_since_any_reading is not None and rz.hours_since_any_reading > PROBE_VERY_STALE_H:
        src_conf = "forecast_only"
    elif rz.hours_since_any_reading is not None and rz.hours_since_any_reading > PROBE_STALE_H:
        src_conf = "stale"
    else:
        src_conf = "fresh"

    return ConfidenceResult(score=conf, level=level, penalties=penalties, warnings=warnings, source_confidence=src_conf)


def _pen(
    current: float,
    penalties: list,
    warnings: list,
    reason: str,
    amount: float,
) -> None:
    """Record a penalty without mutating conf (caller does that)."""
    penalties.append((reason, amount))
    warnings.append(f"-{amount:.2f}: {reason}")


def _apply_depth_quality_penalties(
    rz: RootzoneStatus,
    penalties: list,
    warnings: list,
) -> float:
    """Penalize confidence from actual per-depth probe quality, not a boolean."""
    depths = rz.depth_statuses
    total_depths = len(depths)
    if total_depths == 0:
        return 0.0

    missing = [d for d in depths if d.quality in {"missing", "no_data"} or d.latest_vwc is None]
    stale = [
        d for d in depths
        if d not in missing and (
            d.quality in {"stale", "partial"}
            or (d.hours_since_last is not None and d.hours_since_last > PROBE_STALE_H)
        )
    ]
    suspect = [d for d in depths if d.quality in {"suspect", "invalid"}]
    uncalibrated = [d for d in depths if d.quality == "needs_vwc_calibration"]
    usable = [d for d in depths if _depth_is_usable(d)]

    penalty_total = 0.0

    if missing:
        amount = min(0.18, 0.06 * len(missing))
        _pen(penalty_total, penalties, warnings, f"{len(missing)} probe depth(s) missing", amount)
        penalty_total += amount

    if stale:
        amount = min(0.15, 0.05 * len(stale))
        _pen(penalty_total, penalties, warnings, f"{len(stale)} probe depth(s) stale/partial", amount)
        penalty_total += amount

    if suspect:
        amount = min(0.14, 0.07 * len(suspect))
        _pen(penalty_total, penalties, warnings, f"{len(suspect)} probe depth(s) suspect/invalid", amount)
        penalty_total += amount

    if uncalibrated:
        amount = min(0.20, 0.08 * len(uncalibrated))
        _pen(penalty_total, penalties, warnings, f"{len(uncalibrated)} cBar depth(s) need VWC calibration", amount)
        penalty_total += amount

    usable_ratio = len(usable) / total_depths
    if total_depths >= 2 and usable_ratio < 0.67:
        _pen(penalty_total, penalties, warnings, f"Only {len(usable)}/{total_depths} probe depth(s) usable", 0.10)
        penalty_total += 0.10

    return penalty_total


def _depth_is_usable(depth: DepthStatus) -> bool:
    if depth.latest_vwc is None:
        return False
    if depth.quality in {"missing", "no_data", "stale", "suspect", "invalid", "needs_vwc_calibration"}:
        return False
    if depth.hours_since_last is not None and depth.hours_since_last > PROBE_STALE_H:
        return False
    return True


def _has_severity(anomalies: list, severity: str) -> bool:
    """Check if any anomaly in the list has the given severity.

    Works with both typed Anomaly objects and legacy strings.
    Legacy strings don't carry severity so always return False for specific levels.
    """
    for a in anomalies:
        if hasattr(a, "severity") and a.severity == severity:
            return True
    return False


def _count_severity(anomalies: list, severity: str) -> int:
    return sum(1 for a in anomalies if hasattr(a, "severity") and a.severity == severity)
