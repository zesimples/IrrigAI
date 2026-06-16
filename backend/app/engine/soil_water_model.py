"""Rain-anchored FAO-56 running soil-water balance for probe-less, flowmeter-backed sectors.

Reconstructs current rootzone SWC by integrating a daily water balance forward, crediting
measured irrigation (flowmeter) + rain in and ET0*Kc out. The deep-drainage cap in
apply_daily_balance anchors SWC to field capacity on a large recharge; confidence reflects
INPUT COMPLETENESS (weather + flowmeter continuity), not days-since-rain.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.engine.water_balance import (
    DEFAULT_FC,
    DEFAULT_PWP,
    apply_daily_balance,
    compute_depletion,
    compute_taw,
)


@dataclass(frozen=True)
class DayInput:
    day: date
    et0_mm: float | None
    rain_mm: float
    irrigation_mm: float
    weather_gap: bool = False
    irrigation_unmeasured: bool = False


@dataclass(frozen=True)
class SoilWaterModelResult:
    swc_current: float
    depletion_mm: float
    taw_mm: float
    last_anchor_date: date | None
    days_since_anchor: int | None
    seed_kind: str
    n_gap_days: int
    n_days_integrated: int
    confidence_factor: float


_FALLBACK_ET0_MM = 4.0


def _confidence_factor(
    seed_kind: str, n_gap_days: int, n_days: int, days_since_anchor: int | None
) -> float:
    """Confidence in [0.3, 0.9], driven by input completeness — not days-since-rain.

    Base: 0.75 when rain-anchored (the soil was observed at field capacity, so the
    dominant fluxes since then are measured), 0.5 for the static-fallback seed.
    Gap penalty: up to 0.4 removed as the fraction of days with a missing weather or
    flowmeter input rises (unmeasured flux = real accuracy hole).
    Age drift: a small, bounded term (≤0.15 at 365 days) for unmeasured error
    accumulating since the last FC anchor — deliberately slow so a long rainless
    irrigation season holds at "moderate" rather than collapsing.
    Floor 0.3: even a fully-gapped sector still runs the ETc integration.
    """
    if n_days == 0:
        return 0.3
    base = 0.75 if seed_kind == "rain_anchored" else 0.5
    base -= 0.4 * (n_gap_days / n_days)
    if days_since_anchor is not None:
        base -= min(0.15, days_since_anchor / 365 * 0.15)
    return max(0.3, min(0.9, round(base, 3)))


def model_soil_water(
    *,
    fc: float | None,
    pwp: float | None,
    root_depth_m: float,
    kc: float,
    rainfall_effectiveness: float,
    application_efficiency: float = 0.9,
    daily: list[DayInput],
    today: date,
) -> SoilWaterModelResult:
    if root_depth_m <= 0:
        raise ValueError(f"root_depth_m must be > 0, got {root_depth_m!r}")
    fc = fc if fc is not None else DEFAULT_FC
    pwp = pwp if pwp is not None else DEFAULT_PWP
    taw = compute_taw(fc, pwp, root_depth_m)

    swc = pwp + (fc - pwp) * 0.70
    seed_kind = "static_fallback"
    last_anchor: date | None = None
    n_gap = 0
    n_days = 0
    last_et0 = _FALLBACK_ET0_MM

    for d in daily:
        n_days += 1
        day_has_gap = False

        if d.et0_mm is not None and not d.weather_gap:
            last_et0 = d.et0_mm
            et0 = d.et0_mm
        else:
            et0 = last_et0
            day_has_gap = True
        etc = et0 * kc

        rain_eff = max(0.0, d.rain_mm) * rainfall_effectiveness
        if d.irrigation_unmeasured:
            irrig_net = 0.0
            day_has_gap = True
        else:
            irrig_net = max(0.0, d.irrigation_mm) * application_efficiency

        if day_has_gap:
            n_gap += 1

        swc = apply_daily_balance(swc, etc, rain_eff, irrig_net, fc, root_depth_m)

        if swc >= fc - 1e-6:
            last_anchor = d.day
            seed_kind = "rain_anchored"

    depletion = compute_depletion(fc, swc, root_depth_m)
    days_since_anchor = (today - last_anchor).days if last_anchor is not None else None
    confidence = _confidence_factor(seed_kind, n_gap, n_days, days_since_anchor)

    return SoilWaterModelResult(
        swc_current=round(swc, 4),
        depletion_mm=round(depletion, 2),
        taw_mm=round(taw, 2),
        last_anchor_date=last_anchor,
        days_since_anchor=days_since_anchor,
        seed_kind=seed_kind,
        n_gap_days=n_gap,
        n_days_integrated=n_days,
        confidence_factor=confidence,
    )
