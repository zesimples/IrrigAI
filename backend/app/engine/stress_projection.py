"""48-72h stress projection engine.

Projects rootzone depletion forward 3 days to predict when a sector will
reach the irrigation trigger (MAD threshold).

Applies the FAO-56 water stress coefficient Ks when depletion already
exceeds RAW — a stressed crop transpires less, so the projection is not
as pessimistic as assuming full ETc throughout.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class DayProjection:
    date: date
    projected_etc_mm: float
    projected_rain_mm: float
    projected_depletion_mm: float
    projected_depletion_pct: float
    stress_triggered: bool


@dataclass
class StressProjection:
    sector_id: str | None
    current_depletion_pct: float
    projections: list[DayProjection]
    hours_to_stress: float | None       # None if no stress in 72h
    stress_date: date | None
    urgency: str                        # "none", "low" (48-72h), "medium" (24-48h), "high" (<24h)
    message_pt: str
    message_en: str


def _compute_ks(depletion_mm: float, taw_mm: float, mad: float) -> float:
    """FAO-56 water stress coefficient Ks.

    Ks = 1.0 when depletion ≤ RAW (no stress — crop transpires at full rate).
    Ks = (TAW − Dr) / ((1 − p) × TAW) when depletion > RAW.

    This reflects that a water-stressed crop reduces stomatal conductance
    and transpires at a lower rate, slowing further depletion.
    """
    raw = mad * taw_mm
    if depletion_mm <= raw or taw_mm <= 0:
        return 1.0
    non_stressed_fraction = (1.0 - mad) * taw_mm
    if non_stressed_fraction <= 0:
        return 0.0
    return max(0.0, min(1.0, (taw_mm - depletion_mm) / non_stressed_fraction))


class StressProjector:
    """Projects rootzone depletion forward 48-72h."""

    def project(
        self,
        current_depletion_mm: float,
        taw_mm: float,
        mad: float,
        forecast_et0: list[float | None],
        kc: float,
        forecast_rain: list[tuple[float, float]],   # (mm, probability_pct)
        rainfall_effectiveness: float = 0.8,
        sector_id: str | None = None,
        today: date | None = None,
    ) -> StressProjection:
        if today is None:
            from datetime import date as _date
            today = _date.today()

        stress_threshold_mm = mad * taw_mm
        current_pct = round(current_depletion_mm / taw_mm * 100, 1) if taw_mm > 0 else 0.0

        depletion = current_depletion_mm
        projections: list[DayProjection] = []
        hours_to_stress: float | None = None
        stress_date: date | None = None

        # Use the first available forecast ET0 as fallback for missing days
        fallback_et0 = next((e for e in forecast_et0 if e is not None), 4.0)

        for day_idx in range(3):
            proj_date = today + timedelta(days=day_idx + 1)

            et0 = (
                forecast_et0[day_idx]
                if day_idx < len(forecast_et0) and forecast_et0[day_idx] is not None
                else fallback_et0
            )

            # Apply Ks: stressed crop transpires less, slowing depletion
            ks = _compute_ks(depletion, taw_mm, mad)
            etc = round(et0 * kc * ks, 2)

            rain_mm = 0.0
            if day_idx < len(forecast_rain):
                rain_val, rain_prob = forecast_rain[day_idx]
                if rain_prob > 50.0:
                    rain_mm = round(rain_val * rainfall_effectiveness, 2)

            depletion = depletion + etc - rain_mm
            depletion = max(0.0, min(taw_mm, depletion))

            stress = depletion >= stress_threshold_mm
            depletion_pct = round(depletion / taw_mm * 100, 1) if taw_mm > 0 else 0.0

            projections.append(DayProjection(
                date=proj_date,
                projected_etc_mm=etc,
                projected_rain_mm=rain_mm,
                projected_depletion_mm=round(depletion, 2),
                projected_depletion_pct=depletion_pct,
                stress_triggered=stress,
            ))

            if stress and hours_to_stress is None:
                stress_date = proj_date
                prev_depletion = (
                    projections[day_idx - 1].projected_depletion_mm
                    if day_idx > 0
                    else current_depletion_mm
                )
                delta = depletion - prev_depletion
                gap = stress_threshold_mm - prev_depletion
                fraction = gap / delta if delta > 0 else 1.0
                hours_to_stress = round((day_idx + fraction) * 24, 1)

        urgency = _classify_urgency(hours_to_stress)
        message_pt, message_en = _build_messages(urgency, hours_to_stress, stress_date)

        return StressProjection(
            sector_id=sector_id,
            current_depletion_pct=current_pct,
            projections=projections,
            hours_to_stress=hours_to_stress,
            stress_date=stress_date,
            urgency=urgency,
            message_pt=message_pt,
            message_en=message_en,
        )


def _classify_urgency(hours: float | None) -> str:
    if hours is None:
        return "none"
    if hours < 24:
        return "high"
    if hours < 48:
        return "medium"
    return "low"


def _build_messages(urgency: str, hours: float | None, stress_date: date | None) -> tuple[str, str]:
    if urgency == "none":
        return (
            "Sem risco de stress hídrico nas próximas 72 horas.",
            "No water stress risk in the next 72 hours.",
        )
    h = round(hours) if hours is not None else "?"
    date_str = stress_date.strftime("%-d %b") if stress_date else ""
    if urgency == "high":
        return (
            f"Stress hídrico previsto em ~{h}h ({date_str}). Recomenda-se rega imediata.",
            f"Water stress expected in ~{h}h ({date_str}). Irrigation recommended now.",
        )
    if urgency == "medium":
        return (
            f"Stress hídrico provável em ~{h}h ({date_str}). Planeie rega nas próximas horas.",
            f"Water stress likely in ~{h}h ({date_str}). Plan irrigation within the next hours.",
        )
    return (
        f"Stress hídrico possível em ~{h}h ({date_str}) se não houver rega.",
        f"Water stress possible in ~{h}h ({date_str}) without irrigation.",
    )
