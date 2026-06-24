"""Soil reference-point (FC / lower bound) resolution.

Precedence: probe-calibrated envelope > SCP value > plot/preset > default.

Calibration is measured from the sector's own probe envelope and is the most
authoritative FC we have, so it outranks the configured SCP/plot values — those
are auto-populated from generic soil-texture presets on every sector (the very
thing that caused the "always 100%" pin), not deliberate per-sector overrides.
A future explicit "FC locked by user" flag would be the only thing to rank above
calibration. Kept pure and separate from build_sector_context so the precedence
is unit-testable without a DB session.
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
    # 1. Probe-calibrated bounds — measured from the sector's own sensor, most
    #    authoritative. Calibrate FC *and* the lower bound together, so TAW shrinks
    #    to the real operating band instead of ballooning against PWP. Outranks the
    #    configured SCP/plot values, which are preset-derived (the pinning cause),
    #    not deliberate overrides.
    if calib_fc is not None and calib_refill is not None:
        return ResolvedSoilBounds(calib_fc, calib_refill, "probe_calibrated", calib_meta)
    # 2. SCP value (per-sector soil config).
    if scp_fc is not None and scp_pwp is not None:
        return ResolvedSoilBounds(scp_fc, scp_pwp, "scp", None)
    # 3. Plot / preset.
    if plot_fc is not None and plot_pwp is not None:
        return ResolvedSoilBounds(plot_fc, plot_pwp, "plot_preset", None)
    # 4. Hardcoded clay-loam default — last resort.
    return ResolvedSoilBounds(DEFAULT_FC, DEFAULT_PWP, "default", None)
