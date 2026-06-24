"""Soil reference-point (FC / lower bound) resolution.

Precedence: explicit SCP override > probe-calibrated envelope > plot/preset > default.
Kept pure and separate from build_sector_context so the precedence is unit-testable
without a DB session.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_FC = 0.28   # clay-loam last-resort fallback (matches water_balance.DEFAULT_FC)
DEFAULT_PWP = 0.14


@dataclass
class ResolvedSoilBounds:
    fc: float
    pwp: float                  # lower bound: PWP, or the calibrated refill line
    source: str                 # "scp" | "probe_calibrated" | "plot_preset" | "default"
    calibration: dict | None    # metadata when source == "probe_calibrated"


def resolve_soil_bounds(
    *,
    scp_fc: float | None,
    scp_pwp: float | None,
    calib_fc: float | None,
    calib_refill: float | None,
    calib_meta: dict | None,
    plot_fc: float | None,
    plot_pwp: float | None,
) -> ResolvedSoilBounds:
    # 1. Explicit SCP override (user-set) — highest precedence.
    if scp_fc is not None and scp_pwp is not None:
        return ResolvedSoilBounds(scp_fc, scp_pwp, "scp", None)
    # 2. Probe-calibrated bounds — calibrate FC *and* the lower bound together, so
    #    TAW shrinks to the real operating band instead of ballooning against PWP.
    if calib_fc is not None and calib_refill is not None:
        return ResolvedSoilBounds(calib_fc, calib_refill, "probe_calibrated", calib_meta)
    # 3. Plot / preset.
    if plot_fc is not None and plot_pwp is not None:
        return ResolvedSoilBounds(plot_fc, plot_pwp, "plot_preset", None)
    # 4. Hardcoded clay-loam default — last resort.
    return ResolvedSoilBounds(DEFAULT_FC, DEFAULT_PWP, "default", None)
