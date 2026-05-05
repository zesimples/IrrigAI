"""Confidence scoring.

Penalties from 00-project-brief.md, plus user-configuration completeness penalties.
Accepts both legacy string anomaly lists and typed Anomaly objects from the detector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.engine.types import (
    ConfidenceResult,
    ProbeSnapshot,
    SectorContext,
    WeatherContext,
)

if TYPE_CHECKING:
    from app.anomaly.types import Anomaly as AnomalyObj

PROBE_STALE_H = 6.0
WEATHER_STALE_H = 24.0

# Anomaly severity penalties
_ANOMALY_CRITICAL_PENALTY = 0.20
_ANOMALY_WARNING_PENALTY = 0.10


def score(
    ctx: SectorContext,
    probes: ProbeSnapshot,
    weather: WeatherContext,
    anomalies: list[str] | list[AnomalyObj] | None = None,
) -> ConfidenceResult:
    """Compute confidence score for a recommendation.

    Returns a ConfidenceResult with score, level, per-penalty breakdown, and warnings.
    """
    conf = 1.0
    penalties: list[tuple[str, float]] = []
    warnings: list[str] = []

    # --- Probe data quality ---
    rz = probes.rootzone
    if not rz.has_data:
        _pen(conf, penalties, warnings, "No probe data", 0.25)
        conf -= 0.25
    elif rz.hours_since_any_reading is not None and rz.hours_since_any_reading > PROBE_STALE_H:
        _pen(conf, penalties, warnings, f"Probe data stale ({rz.hours_since_any_reading:.1f}h)", 0.25)
        conf -= 0.25

    if not rz.all_depths_ok and rz.has_data:
        _pen(conf, penalties, warnings, "Some probe depths missing/suspect", 0.10)
        conf -= 0.10

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
    elif rz.hours_since_any_reading is not None and rz.hours_since_any_reading > 24:
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
