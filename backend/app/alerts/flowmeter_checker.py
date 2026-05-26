# backend/app/alerts/flowmeter_checker.py
"""Flowmeter deviation alert checker.

Detects sectors whose per-day water consumption deviates more than ±5%
from the crop-average. Works directly on FlowmeterReading rows:

  Sub-hourly flowmeters (median interval < HOURLY_THRESHOLD_MINUTES):
    For each (flowmeter, calendar-day):
      - Sort readings by timestamp
      - Strip the first and last reading (partial valve-open/close intervals)
      - Sum the interior readings → clean daily total
      - Days with fewer than 3 readings are skipped (cannot form an interior)

  Hourly flowmeters (median interval ≥ HOURLY_THRESHOLD_MINUTES):
    Outlier stripping is skipped — with only ~1 reading/h there is no meaningful
    spin-up noise to remove. All readings in each day are summed directly.

  A sector needs at least MIN_INTERIOR_DAYS valid day-totals to be evaluated;
  otherwise it is flagged as insufficient_data.
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertSeverity, AlertType
from app.models.alert import Alert

logger = logging.getLogger(__name__)

PERIOD_DAYS = 7
DEVIATION_THRESHOLD_PCT = 5.0
MIN_INTERIOR_DAYS = 2

# Flowmeters whose median reading interval is at or above this value (minutes)
# are treated as hourly — outlier stripping is skipped for them.
_HOURLY_THRESHOLD_MINUTES: float = 45.0


def _infer_median_interval(readings: list) -> float:
    """Return the median gap (minutes) between consecutive readings.

    Falls back to 15.0 if the interval cannot be determined (< 2 readings).
    Readings must already be sorted by timestamp.
    """
    if len(readings) < 2:
        return 15.0
    gaps = sorted(
        (readings[i + 1].timestamp - readings[i].timestamp).total_seconds() / 60
        for i in range(len(readings) - 1)
        if (readings[i + 1].timestamp - readings[i].timestamp).total_seconds() > 0
    )
    if not gaps:
        return 15.0
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 == 1 else (gaps[mid - 1] + gaps[mid]) / 2


@dataclass
class _SectorResult:
    sector_id: str
    sector_name: str
    crop_type: str
    interior_days: list[float]   # per-day sums of interior readings (outliers stripped)
    interior_avg: float | None   # mean of interior_days; None if < MIN_INTERIOR_DAYS


@dataclass
class _ComputeResult:
    sector_results: list[_SectorResult]
    crop_averages: dict[str, float]


def _alert(
    alert_type: AlertType,
    severity: AlertSeverity,
    title_pt: str,
    title_en: str,
    description_pt: str,
    description_en: str,
    farm_id: str,
    sector_id: str,
    data: dict,
) -> Alert:
    return Alert(
        alert_type=alert_type,
        severity=severity,
        title_pt=title_pt,
        title_en=title_en,
        description_pt=description_pt,
        description_en=description_en,
        farm_id=farm_id,
        sector_id=sector_id,
        is_active=True,
        data=data,
    )


class FlowmeterAlertChecker:
    """Check for flowmeter consumption deviations vs per-crop interior-reading averages."""

    async def check(self, farm_id: str, db: AsyncSession) -> list[Alert]:
        """Compute deviations and return Alert objects. Does NOT write to DB."""
        result = await self._compute(farm_id, db)
        return self._build_alerts(result, farm_id)

    async def compute_deviations(self, farm_id: str, db: AsyncSession):
        """Compute deviations and return structured response for the frontend."""
        from app.schemas.flowmeter import (
            FlowmeterDeviationSector,
            FlowmeterDeviationsResponse,
            FlowmeterInsufficientDataSector,
        )
        result = await self._compute(farm_id, db)
        deviating = []
        insufficient_data = []

        for sr in result.sector_results:
            if sr.interior_avg is None:
                insufficient_data.append(
                    FlowmeterInsufficientDataSector(
                        sector_id=sr.sector_id,
                        sector_name=sr.sector_name,
                        crop_type=sr.crop_type,
                        interior_day_count=len(sr.interior_days),
                    )
                )
                continue

            crop_avg = result.crop_averages.get(sr.crop_type)
            if crop_avg is None:
                continue

            deviation_pct = (sr.interior_avg - crop_avg) / crop_avg * 100
            if abs(deviation_pct) > DEVIATION_THRESHOLD_PCT:
                deviating.append(
                    FlowmeterDeviationSector(
                        sector_id=sr.sector_id,
                        sector_name=sr.sector_name,
                        crop_type=sr.crop_type,
                        direction="above" if deviation_pct > 0 else "below",
                        deviation_pct=round(deviation_pct, 1),
                        sector_avg_m3ha=round(sr.interior_avg, 2),
                        crop_avg_m3ha=round(crop_avg, 2),
                        interior_day_count=len(sr.interior_days),
                    )
                )

        return FlowmeterDeviationsResponse(
            period_days=PERIOD_DAYS,
            deviating=deviating,
            insufficient_data=insufficient_data,
            crop_averages={k: round(v, 2) for k, v in result.crop_averages.items()},
            evaluated_at=datetime.now(UTC),
        )

    def _compute_from_data(self, pairs: list, all_readings: list) -> _ComputeResult:
        """Compute interior day totals and crop means. Testable without DB.

        Infers the reading interval per flowmeter from the full dataset and applies
        different day-aggregation strategies:
          - Sub-hourly (< HOURLY_THRESHOLD_MINUTES): strip first+last per day, need ≥3 readings.
          - Hourly (≥ HOURLY_THRESHOLD_MINUTES): sum all readings per day, no stripping.
        """
        # Classify each flowmeter's interval from its full reading set.
        all_fm_readings: dict[str, list] = defaultdict(list)
        for r in all_readings:
            all_fm_readings[str(r.flowmeter_id)].append(r)

        fm_is_hourly: dict[str, bool] = {}
        for fm_id, fm_readings in all_fm_readings.items():
            sorted_all = sorted(fm_readings, key=lambda r: r.timestamp)
            interval = _infer_median_interval(sorted_all)
            fm_is_hourly[fm_id] = interval >= _HOURLY_THRESHOLD_MINUTES
            logger.debug(
                "flowmeter %s: median interval %.1f min → %s",
                fm_id, interval, "hourly" if fm_is_hourly[fm_id] else "sub-hourly",
            )

        readings_by_fm_date: dict[tuple, list] = defaultdict(list)
        for r in all_readings:
            day = r.timestamp.astimezone(timezone.utc).date()
            readings_by_fm_date[(str(r.flowmeter_id), day)].append(r)

        day_totals_by_fm: dict[str, list[float]] = defaultdict(list)
        for (fm_id, _day), day_readings in readings_by_fm_date.items():
            sorted_day = sorted(day_readings, key=lambda r: r.timestamp)
            if fm_is_hourly.get(fm_id, False):
                # Hourly: no spin-up noise to strip — use all readings.
                if sorted_day:
                    day_totals_by_fm[fm_id].append(sum(r.value_m3_ha for r in sorted_day))
            else:
                # Sub-hourly: strip first+last; need ≥3 readings to have ≥1 interior.
                if len(sorted_day) >= 3:
                    interior = sorted_day[1:-1]
                    day_totals_by_fm[fm_id].append(sum(r.value_m3_ha for r in interior))

        sector_results: list[_SectorResult] = []
        for fm, sector in pairs:
            fm_id = str(fm.id)
            day_totals = day_totals_by_fm.get(fm_id, [])
            avg: float | None = (
                statistics.mean(day_totals)
                if len(day_totals) >= MIN_INTERIOR_DAYS
                else None
            )
            sector_results.append(
                _SectorResult(
                    sector_id=str(sector.id),
                    sector_name=sector.name,
                    crop_type=sector.crop_type or "unknown",
                    interior_days=day_totals,
                    interior_avg=avg,
                )
            )

        crop_avgs_raw: dict[str, list[float]] = defaultdict(list)
        for sr in sector_results:
            if sr.interior_avg is not None:
                crop_avgs_raw[sr.crop_type].append(sr.interior_avg)

        crop_averages = {
            crop: statistics.mean(avgs)
            for crop, avgs in crop_avgs_raw.items()
            if avgs
        }
        return _ComputeResult(sector_results=sector_results, crop_averages=crop_averages)

    def _build_alerts(self, result: _ComputeResult, farm_id: str) -> list[Alert]:
        alerts: list[Alert] = []
        for sr in result.sector_results:
            if sr.interior_avg is None:
                alerts.append(_alert(
                    alert_type=AlertType.FLOWMETER_INSUFFICIENT_DATA,
                    severity=AlertSeverity.INFO,
                    title_pt=f"Dados insuficientes: {sr.sector_name}",
                    title_en=f"Insufficient data: {sr.sector_name}",
                    description_pt=(
                        f"{sr.sector_name} tem apenas {len(sr.interior_days)} dia(s) "
                        f"com leituras interiores nos últimos {PERIOD_DAYS} dias. "
                        f"São necessários pelo menos {MIN_INTERIOR_DAYS} para avaliação."
                    ),
                    description_en=(
                        f"{sr.sector_name} has only {len(sr.interior_days)} day(s) "
                        f"with interior readings in the last {PERIOD_DAYS} days. "
                        f"At least {MIN_INTERIOR_DAYS} are required for evaluation."
                    ),
                    farm_id=farm_id,
                    sector_id=sr.sector_id,
                    data={"interior_day_count": len(sr.interior_days), "period_days": PERIOD_DAYS},
                ))
                continue

            crop_avg = result.crop_averages.get(sr.crop_type)
            if crop_avg is None:
                continue

            deviation_pct = (sr.interior_avg - crop_avg) / crop_avg * 100
            if abs(deviation_pct) <= DEVIATION_THRESHOLD_PCT:
                continue

            direction = "above" if deviation_pct > 0 else "below"
            direction_pt = "acima" if direction == "above" else "abaixo"
            alerts.append(_alert(
                alert_type=AlertType.FLOWMETER_DEVIATION,
                severity=AlertSeverity.WARNING,
                title_pt=f"Desvio de consumo: {sr.sector_name}",
                title_en=f"Consumption deviation: {sr.sector_name}",
                description_pt=(
                    f"{sr.sector_name} aplica em média {sr.interior_avg:.1f} m³/ha por dia — "
                    f"{abs(deviation_pct):.1f}% {direction_pt} da média da cultura "
                    f"({crop_avg:.1f} m³/ha)."
                ),
                description_en=(
                    f"{sr.sector_name} averages {sr.interior_avg:.1f} m³/ha per day — "
                    f"{abs(deviation_pct):.1f}% {direction} the crop average ({crop_avg:.1f} m³/ha)."
                ),
                farm_id=farm_id,
                sector_id=sr.sector_id,
                data={
                    "deviation_pct": round(deviation_pct, 1),
                    "direction": direction,
                    "sector_avg_m3ha": round(sr.interior_avg, 2),
                    "crop_avg_m3ha": round(crop_avg, 2),
                    "interior_day_count": len(sr.interior_days),
                    "period_days": PERIOD_DAYS,
                },
            ))
        return alerts

    async def _compute(self, farm_id: str, db: AsyncSession) -> _ComputeResult:
        from app.models import Flowmeter, FlowmeterReading, Plot, Sector
        now = datetime.now(UTC)
        since = now - timedelta(days=PERIOD_DAYS)
        fm_result = await db.execute(
            select(Flowmeter, Sector)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .where(Plot.farm_id == farm_id, Flowmeter.is_active.is_(True))
        )
        pairs = fm_result.all()
        if not pairs:
            return _ComputeResult(sector_results=[], crop_averages={})
        fm_ids = [str(fm.id) for fm, _ in pairs]
        readings_result = await db.execute(
            select(FlowmeterReading)
            .where(
                FlowmeterReading.flowmeter_id.in_(fm_ids),
                FlowmeterReading.timestamp >= since,
            )
            .order_by(FlowmeterReading.timestamp)
        )
        all_readings = readings_result.scalars().all()
        return self._compute_from_data(pairs, all_readings)
