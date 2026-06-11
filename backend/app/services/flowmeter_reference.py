"""Flowmeter reference flow rate service.

Pure computation functions + DB-backed service for establishing and managing
per-sector reference flow rates used for irrigation anomaly detection.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MIN_EVENTS_ESTABLISHED = 5
MIN_EVENTS_PROVISIONAL = 3


@dataclass
class StableRateResult:
    stable_rate_m3_ha: float | None
    std_dev: float
    num_readings_used: int
    status: str  # "ok", "too_short"


def compute_stable_flow_rate(
    readings: list[tuple[datetime, float]],
    trim_start: int = 2,
    trim_end: int = 2,
    min_readings: int = 3,
) -> StableRateResult:
    """Compute the stable flow rate from raw readings within one irrigation event.

    Sorts readings by timestamp, discards the first `trim_start` (ramp-up) and
    last `trim_end` (ramp-down), then returns the mean of what remains.
    Returns status="too_short" if fewer than `min_readings` remain after trimming.
    """
    if not readings:
        return StableRateResult(None, 0.0, 0, "too_short")
    sorted_r = sorted(readings, key=lambda t: t[0])
    end = len(sorted_r) - trim_end if trim_end > 0 else len(sorted_r)
    trimmed = sorted_r[trim_start:end]
    if len(trimmed) < min_readings:
        return StableRateResult(None, 0.0, len(trimmed), "too_short")
    values = [v for _, v in trimmed]
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return StableRateResult(round(mean, 4), round(std, 4), len(trimmed), "ok")


def compute_reference_from_stable_rates(
    stable_rates: list[float],
    tolerance_pct: float = 5.0,
) -> dict:
    """Compute a reference dict from a list of per-event stable rates.

    Returns a dict with keys:
        reference_rate_m3_ha: float | None
        upper_limit_m3_ha: float | None
        lower_limit_m3_ha: float | None
        std_dev: float
        num_events: int
        status: "established" | "provisional" | "insufficient"
    """
    n = len(stable_rates)
    if n < MIN_EVENTS_PROVISIONAL:
        return {
            "reference_rate_m3_ha": None,
            "upper_limit_m3_ha": None,
            "lower_limit_m3_ha": None,
            "std_dev": 0.0,
            "num_events": n,
            "status": "insufficient",
        }
    ref = statistics.median(stable_rates)
    std = statistics.stdev(stable_rates) if n > 1 else 0.0
    upper = round(ref * (1 + tolerance_pct / 100), 4)
    lower = round(ref * (1 - tolerance_pct / 100), 4)
    status = "established" if n >= MIN_EVENTS_ESTABLISHED else "provisional"
    return {
        "reference_rate_m3_ha": round(ref, 4),
        "upper_limit_m3_ha": upper,
        "lower_limit_m3_ha": lower,
        "std_dev": round(std, 4),
        "num_events": n,
        "status": status,
    }
