"""Irrigation dosage computation.

Computes gross water depth and runtime from water balance and irrigation system config.
Returns None for runtime when irrigation system is not configured.
"""

from dataclasses import dataclass

from app.engine.types import SectorContext
from app.engine.water_balance import WaterBalanceResult
from app.utils.units import drip_application_rate, runtime_hours


@dataclass
class DosageResult:
    irrigation_net_mm: float            # mm needed to refill to FC
    irrigation_gross_mm: float          # net / efficiency
    runtime_min: float | None           # None if system not configured
    application_rate_mm_h: float | None
    capped: bool = False                # True if capped by min/max constraints
    cap_reason: str | None = None


def compute_dosage(wb: WaterBalanceResult, ctx: SectorContext) -> DosageResult:
    """Compute irrigation depth and runtime.

    Depth = depletion (refill to FC).
    Gross = net / efficiency.
    Runtime = gross / application_rate (requires irrigation system config).
    """
    net_mm = wb.depletion_mm
    efficiency = ctx.irrigation_efficiency if ctx.irrigation_efficiency > 0 else 0.90
    gross_mm = net_mm / efficiency

    capped = False
    cap_reason = None

    # Apply min/max irrigation constraints
    if ctx.min_irrigation_mm is not None and gross_mm < ctx.min_irrigation_mm:
        gross_mm = ctx.min_irrigation_mm
        net_mm = gross_mm * efficiency
        capped = True
        cap_reason = f"Below minimum ({ctx.min_irrigation_mm}mm gross)"
    if ctx.max_irrigation_mm is not None and gross_mm > ctx.max_irrigation_mm:
        gross_mm = ctx.max_irrigation_mm
        net_mm = gross_mm * efficiency
        capped = True
        cap_reason = f"Capped at maximum ({ctx.max_irrigation_mm}mm gross)"

    # Determine application rate
    app_rate = ctx.application_rate_mm_h

    # If application rate not stored, try to compute from emitter config
    if app_rate is None and ctx.emitter_flow_lph and ctx.emitter_spacing_m and ctx.row_spacing_m:
        try:
            app_rate = drip_application_rate(
                emitter_flow_l_h=ctx.emitter_flow_lph,
                emitter_spacing_m=ctx.emitter_spacing_m,
                row_spacing_m=ctx.row_spacing_m,
            )
        except ValueError:
            app_rate = None

    # Compute runtime
    runtime_min = None
    if app_rate is not None and app_rate > 0:
        hours = runtime_hours(gross_mm, app_rate)
        runtime_min = round(hours * 60, 1)

        # Cap by max_runtime_hours if set
        if ctx.max_runtime_hours is not None:
            max_min = ctx.max_runtime_hours * 60
            if runtime_min > max_min:
                runtime_min = max_min
                capped = True
                cap_reason = f"Capped at max runtime ({ctx.max_runtime_hours}h)"

    return DosageResult(
        irrigation_net_mm=round(net_mm, 2),
        irrigation_gross_mm=round(gross_mm, 2),
        runtime_min=runtime_min,
        application_rate_mm_h=round(app_rate, 3) if app_rate is not None else None,
        capped=capped,
        cap_reason=cap_reason,
    )
