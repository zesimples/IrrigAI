"""Daily water balance model.

SWC(t) = SWC(t-1) + Rain_effective + Irrigation_net - ETc - DeepDrainage

Uses FC, PWP, and root_depth from SectorContext (user-configured).
"""

from dataclasses import dataclass

from app.engine.types import SectorContext

# Fallback soil parameters when user hasn't configured soil (clay-loam defaults)
DEFAULT_FC = 0.28
DEFAULT_PWP = 0.14


@dataclass
class WaterBalanceResult:
    swc_current: float          # m³/m³
    depletion_mm: float         # (FC - SWC) × root_depth × 1000
    taw_mm: float               # Total available water (FC - PWP) × root_depth × 1000
    raw_mm: float               # Readily available water = TAW × MAD
    fc: float                   # FC used
    pwp: float                  # PWP used
    root_depth_m: float


def compute_taw(fc: float, pwp: float, root_depth_m: float) -> float:
    """Total available water (mm)."""
    return max(0.0, (fc - pwp) * root_depth_m * 1000)


def compute_raw(taw: float, mad: float) -> float:
    """Readily available water (mm) = TAW × MAD."""
    return taw * mad


def compute_depletion(fc: float, swc: float, root_depth_m: float) -> float:
    """Root zone depletion Dr (mm) = (FC - SWC) × root_depth × 1000."""
    return max(0.0, (fc - swc) * root_depth_m * 1000)


def apply_daily_balance(
    swc_prev: float,
    etc_mm: float,
    rainfall_effective_mm: float,
    irrigation_net_mm: float,
    fc: float,
    root_depth_m: float,
) -> float:
    """Apply one day of water balance, return new SWC.

    Caps at FC (deep drainage removes excess), floors at ~0.
    """
    swc_new = swc_prev + (rainfall_effective_mm + irrigation_net_mm - etc_mm) / (root_depth_m * 1000)
    # Deep drainage: cap at FC
    swc_new = min(fc, swc_new)
    # Can't go below zero
    swc_new = max(0.001, swc_new)
    return round(swc_new, 4)


def build_water_balance(ctx: SectorContext, swc_probe: float | None) -> WaterBalanceResult:
    """Build current water balance state from context and probe data.

    If probe SWC is available, uses it as current state (probe is authoritative).
    Otherwise falls back to initialising at 70% of TAW.
    """
    fc = ctx.field_capacity if ctx.field_capacity is not None else DEFAULT_FC
    pwp = ctx.wilting_point if ctx.wilting_point is not None else DEFAULT_PWP
    root_depth_m = ctx.root_depth_m

    taw = compute_taw(fc, pwp, root_depth_m)
    raw = compute_raw(taw, ctx.mad)

    if swc_probe is not None:
        swc = max(pwp, min(fc, swc_probe))
    else:
        # No probe data — initialise at 70% of TAW (conservative)
        swc = pwp + (fc - pwp) * 0.70

    depletion = compute_depletion(fc, swc, root_depth_m)

    return WaterBalanceResult(
        swc_current=round(swc, 4),
        depletion_mm=round(depletion, 2),
        taw_mm=round(taw, 2),
        raw_mm=round(raw, 2),
        fc=fc,
        pwp=pwp,
        root_depth_m=root_depth_m,
    )
