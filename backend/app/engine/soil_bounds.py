"""Soil reference-point (FC / lower bound) resolution.

Precedence: user-customized SCP override > probe-calibrated envelope > SCP preset
> plot/preset > default.

A *deliberate* per-sector soil setting (SCP with `is_customized=True`) is the
agronomist's explicit choice and wins over everything. Otherwise probe calibration
— measured from the sector's own envelope — outranks the auto-populated SCP/plot
preset values (those generic soil-texture defaults are what caused the "always
100%" pin, not deliberate overrides). Kept pure and separate from
build_sector_context so the precedence is unit-testable without a DB session.

Recency note: this resolver always lets `is_customized` win; the "last action
wins" behaviour lives at the API layer — the manual /run calibration endpoint
clears `is_customized` so a freshly computed calibration takes precedence, and a
later manual soil/CC-PMP edit re-sets it (see api/v1/auto_calibration.run).
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_FC = 0.28   # clay-loam last-resort fallback (matches water_balance.DEFAULT_FC)
DEFAULT_PWP = 0.14


@dataclass
class ResolvedSoilBounds:
    fc: float
    pwp: float                  # lower bound: PWP, or the calibrated refill line
    source: str                 # "scp_override" | "probe_calibrated" | "scp" | "plot_preset" | "default"
    calibration: dict | None    # metadata when source == "probe_calibrated"


def resolve_soil_bounds(
    *,
    scp_fc: float | None,
    scp_pwp: float | None,
    scp_customized: bool = False,
    calib_fc: float | None,
    calib_refill: float | None,
    calib_meta: dict | None,
    plot_fc: float | None,
    plot_pwp: float | None,
    calib_stale: bool = False,
) -> ResolvedSoilBounds:
    # 1. Deliberate user soil override (SCP edited by a human, is_customized=True) —
    #    the agronomist's explicit choice wins over measured calibration.
    if scp_customized and scp_fc is not None and scp_pwp is not None:
        return ResolvedSoilBounds(scp_fc, scp_pwp, "scp_override", None)
    # 2. Probe-calibrated bounds — measured from the sector's own sensor. Calibrate FC
    #    *and* the lower bound together, so TAW shrinks to the real operating band
    #    instead of ballooning against PWP. Outranks the auto-populated SCP/plot
    #    preset values (the pinning cause). A *stale* calibration (computed_at older
    #    than the max age) is NOT trusted — it falls through to the next source, but
    #    its metadata is still surfaced so the API/UI can explain it was ignored.
    if calib_fc is not None and calib_refill is not None and not calib_stale:
        return ResolvedSoilBounds(calib_fc, calib_refill, "probe_calibrated", calib_meta)
    # 3. SCP value (per-sector soil config, preset-derived / not customized).
    if scp_fc is not None and scp_pwp is not None:
        result = ResolvedSoilBounds(scp_fc, scp_pwp, "scp", None)
    # 4. Plot / preset.
    elif plot_fc is not None and plot_pwp is not None:
        result = ResolvedSoilBounds(plot_fc, plot_pwp, "plot_preset", None)
    # 5. Hardcoded clay-loam default — last resort.
    else:
        result = ResolvedSoilBounds(DEFAULT_FC, DEFAULT_PWP, "default", None)
    # Surface provenance of an ignored (stale) calibration without using its values.
    if calib_stale and calib_meta is not None:
        result.calibration = calib_meta
    return result
