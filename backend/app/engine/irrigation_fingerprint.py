"""Irrigation fingerprint — a sector's habitual irrigation dose learned from
probe-detected irrigation events.

Deterministic (no LLM). Pure math only; the DB-facing loader lives in
services/irrigation_fingerprint_service.py. Powers the "probe_learned" tier of
the dose-do-dia presentation: "≈1.3× a rega habitual".
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

# 25 days: the app is young — a longer window would reach into data that does
# not exist or predates the grower's current routine (spec decision).
FINGERPRINT_WINDOW_DAYS = 25
FINGERPRINT_MAX_AGE_DAYS = 25
MIN_USABLE_EVENTS = 3

_BASELINE_LOOKBACK_H = 3.0
_PEAK_LOOKAHEAD_H = 8.0          # matches the detector's _GROUP_WINDOW_H
_MIN_EVENT_NET_MM = 0.5
_HIGH_CONFIDENCE_MIN_EVENTS = 6
_HIGH_CONFIDENCE_MIN_CONSISTENCY = 0.5


@dataclass(frozen=True)
class EventDose:
    event_timestamp: datetime
    net_mm: float
    duration_min: float | None    # None when readings can't bracket the rise


@dataclass(frozen=True)
class FingerprintResult:
    typical_event_net_mm: float
    typical_event_duration_min: float | None
    n_events: int
    consistency: float            # 1 − IQR/median of event doses, clamped [0, 1]
    confidence: str               # "medium" | "high"
    window_days: int


def layer_thicknesses_mm(
    depths_cm: list[int], root_depth_cm: float | None = None
) -> dict[int, float]:
    """mm of soil each sensor represents (depth-interval method).

    Mirrors probe_interpreter._depth_interval_weights: each sensor spans from
    the midpoint to its shallower neighbour (or the surface) down to the
    midpoint to its deeper neighbour (or its own depth + half the last gap),
    optionally capped at the root zone.
    """
    ds = sorted(set(depths_cm))
    if not ds:
        return {}
    layers: dict[int, float] = {}
    for i, d in enumerate(ds):
        upper = 0.0 if i == 0 else (ds[i - 1] + d) / 2
        if i < len(ds) - 1:
            lower = (d + ds[i + 1]) / 2
        else:
            last_gap = float(d - ds[i - 1]) if len(ds) > 1 else float(d)
            lower = d + last_gap / 2
        if root_depth_cm is not None:
            lower = min(lower, root_depth_cm)
        layers[d] = max(0.0, (lower - upper) * 10.0)  # cm → mm
    return layers


def compute_event_dose(
    series_by_depth: dict[int, list[tuple[datetime, float]]],
    event_ts: datetime,
    layers_mm: dict[int, float],
) -> EventDose | None:
    """Net mm delivered by one irrigation event, integrated over depths.

    Baseline = min VWC in the 3h before the event; peak = max VWC in the 8h
    after; per-depth delta clamped at ≥ 0. Duration = event start → latest
    per-depth peak (quantized by the probe's reading interval).
    """
    total_mm = 0.0
    peak_times: list[datetime] = []
    for depth_cm, series in series_by_depth.items():
        layer = layers_mm.get(depth_cm)
        if not layer:
            continue
        window_start = event_ts - timedelta(hours=_BASELINE_LOOKBACK_H)
        window_end = event_ts + timedelta(hours=_PEAK_LOOKAHEAD_H)
        before = [v for t, v in series if window_start <= t <= event_ts]
        after = [(t, v) for t, v in series if event_ts < t <= window_end]
        if not before or not after:
            continue
        baseline = min(before)
        peak_t, peak_v = max(after, key=lambda tv: tv[1])
        delta = peak_v - baseline
        if delta > 0:
            total_mm += delta * layer
            peak_times.append(peak_t)
    if total_mm < _MIN_EVENT_NET_MM:
        return None
    duration_min: float | None = None
    if peak_times:
        minutes = (max(peak_times) - event_ts).total_seconds() / 60.0
        duration_min = round(minutes, 1) if minutes > 0 else None
    return EventDose(
        event_timestamp=event_ts, net_mm=round(total_mm, 2), duration_min=duration_min
    )


def compute_fingerprint(
    doses: list[EventDose], window_days: int = FINGERPRINT_WINDOW_DAYS
) -> FingerprintResult | None:
    if len(doses) < MIN_USABLE_EVENTS:
        return None
    nets = sorted(d.net_mm for d in doses)
    median_net = statistics.median(nets)
    if median_net <= 0:
        return None
    if len(nets) >= 4:
        q = statistics.quantiles(nets, n=4)
        iqr = q[2] - q[0]
    else:
        iqr = nets[-1] - nets[0]
    consistency = max(0.0, min(1.0, 1.0 - iqr / median_net))
    durations = [d.duration_min for d in doses if d.duration_min is not None]
    typical_duration = (
        round(statistics.median(durations), 0) if len(durations) >= MIN_USABLE_EVENTS else None
    )
    confidence = (
        "high"
        if len(doses) >= _HIGH_CONFIDENCE_MIN_EVENTS
        and consistency >= _HIGH_CONFIDENCE_MIN_CONSISTENCY
        else "medium"
    )
    return FingerprintResult(
        typical_event_net_mm=round(median_net, 2),
        typical_event_duration_min=typical_duration,
        n_events=len(doses),
        consistency=round(consistency, 3),
        confidence=confidence,
        window_days=window_days,
    )


def is_fingerprint_stale(computed_at: datetime, now: datetime) -> bool:
    return (now - computed_at).days >= FINGERPRINT_MAX_AGE_DAYS
