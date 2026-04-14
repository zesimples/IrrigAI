"""Irrigation trigger logic.

Decides whether irrigation is needed based on root zone depletion vs. RAW.
Also handles RDI (Regulated Deficit Irrigation) strategy.
"""

from app.engine.types import SectorContext
from app.engine.water_balance import WaterBalanceResult


def should_irrigate(
    wb: WaterBalanceResult,
    ctx: SectorContext,
    forecast_rain_next_48h: float = 0.0,
) -> tuple[bool, str]:
    """Determine if irrigation should be triggered.

    Returns (trigger, reason_en).

    Logic:
    - SKIP if forecast rain > 15mm in next 48h
    - RDI: if rdi_eligible and strategy == "rdi", use rdi_factor × RAW as threshold
    - IRRIGATE if Dr >= RAW
    - SKIP otherwise
    """
    raw = wb.raw_mm
    dr = wb.depletion_mm

    # Rain skip
    if forecast_rain_next_48h >= 15.0:
        return False, f"Rega adiada — previsão de {forecast_rain_next_48h:.0f} mm de chuva nas próximas 48h"

    # RDI strategy — apply deficit factor to threshold
    effective_threshold = raw
    if ctx.irrigation_strategy == "rdi" and ctx.rdi_eligible and ctx.rdi_factor is not None:
        effective_threshold = raw * ctx.rdi_factor
    elif ctx.deficit_factor < 1.0:
        effective_threshold = raw * ctx.deficit_factor

    if dr >= effective_threshold:
        pct_depleted = dr / wb.taw_mm * 100 if wb.taw_mm > 0 else 0
        return True, f"Depleção {dr:.1f} mm ≥ limiar {effective_threshold:.1f} mm ({pct_depleted:.0f}% da TAW esgotada)"

    remaining = effective_threshold - dr
    return False, f"Solo com reserva suficiente — faltam {remaining:.1f} mm para atingir o limiar de rega"
