"""Irrigation trigger logic.

Decides whether irrigation is needed based on root zone depletion vs. RAW.
Also handles RDI (Regulated Deficit Irrigation) strategy.

Rain skip is physics-based: forecast rain is only credited at the configured
rainfall_effectiveness, and a skip is only recommended if that effective rain
actually covers the remaining deficit — not based on a hardcoded mm threshold.
"""

from app.engine.types import SectorContext
from app.engine.water_balance import WaterBalanceResult

# Minimum effective rain that justifies a skip (mm) — prevents skipping for
# inconsequential drizzle even when depletion is already near zero.
_MIN_EFFECTIVE_RAIN_TO_SKIP = 3.0


def should_irrigate(
    wb: WaterBalanceResult,
    ctx: SectorContext,
    forecast_rain_next_48h: float = 0.0,
) -> tuple[bool, str]:
    """Determine if irrigation should be triggered.

    Returns (trigger, reason_pt).

    Logic:
    - Compute effective irrigation threshold (RDI / deficit strategies)
    - SKIP if expected effective rain (rain × rainfall_effectiveness) covers
      the remaining deficit to the trigger threshold
    - IRRIGATE if Dr >= threshold
    - SKIP otherwise
    """
    raw = wb.raw_mm
    dr = wb.depletion_mm

    # Effective threshold — adjusted for RDI or deficit irrigation strategy
    effective_threshold = raw
    if ctx.irrigation_strategy == "rdi" and ctx.rdi_eligible and ctx.rdi_factor is not None:
        effective_threshold = raw * ctx.rdi_factor
    elif ctx.deficit_factor < 1.0:
        effective_threshold = raw * ctx.deficit_factor

    # Physics-based rain skip
    if forecast_rain_next_48h > 0:
        effective_rain = forecast_rain_next_48h * ctx.rainfall_effectiveness
        remaining_to_trigger = max(0.0, effective_threshold - dr)
        if effective_rain >= remaining_to_trigger and effective_rain >= _MIN_EFFECTIVE_RAIN_TO_SKIP:
            return False, (
                f"Chuva prevista de {forecast_rain_next_48h:.0f} mm nas próximas 48h "
                f"({effective_rain:.1f} mm efetivos) cobre o défice atual — não vale a pena regar agora"
            )

    if dr >= effective_threshold:
        pct_depleted = dr / wb.taw_mm * 100 if wb.taw_mm > 0 else 0
        return True, (
            f"O solo já perdeu {pct_depleted:.0f}% da água disponível "
            f"({dr:.1f} mm em falta) — chegou a hora de regar"
        )

    remaining = effective_threshold - dr
    return False, f"O solo ainda tem reserva suficiente — faltam {remaining:.1f} mm para atingir o ponto de rega"
