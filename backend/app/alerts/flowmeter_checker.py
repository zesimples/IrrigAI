# backend/app/alerts/flowmeter_checker.py
"""Flowmeter deviation alert checker.

Detects sectors whose per-event water consumption deviates more than ±5%
from the crop-average of interior events. Strips the first and last event
per sector per calendar day (system spin-up / wind-down outliers).
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertSeverity, AlertType
from app.models.alert import Alert

logger = logging.getLogger(__name__)

PERIOD_DAYS = 7
DEVIATION_THRESHOLD_PCT = 5.0
MIN_INTERIOR_EVENTS = 3


@dataclass
class _SectorResult:
    sector_id: str
    sector_name: str
    crop_type: str
    interior_events: list
    interior_avg: float | None


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
    """Check for flowmeter consumption deviations vs per-crop interior-event averages."""

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
                        interior_event_count=len(sr.interior_events),
                    )
                )
                continue

            crop_avg = result.crop_averages.get(sr.crop_type)
            if not crop_avg:
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
                        interior_event_count=len(sr.interior_events),
                    )
                )

        return FlowmeterDeviationsResponse(
            period_days=PERIOD_DAYS,
            deviating=deviating,
            insufficient_data=insufficient_data,
            crop_averages={k: round(v, 2) for k, v in result.crop_averages.items()},
            evaluated_at=datetime.now(UTC),
        )

    def _compute_from_data(self, pairs: list, all_events: list) -> _ComputeResult:
        """Strip outliers, compute interior averages and crop means. Testable without DB."""
        events_by_fm_date: dict[tuple, list] = defaultdict(list)
        for ev in all_events:
            events_by_fm_date[(str(ev.flowmeter_id), ev.date)].append(ev)

        interior_by_fm: dict[str, list] = defaultdict(list)
        for (fm_id, _day), day_events in events_by_fm_date.items():
            sorted_day = sorted(day_events, key=lambda e: e.start_time)
            if len(sorted_day) >= 2:
                interior_by_fm[fm_id].extend(sorted_day[1:-1])

        sector_results: list[_SectorResult] = []
        for fm, sector in pairs:
            fm_id = str(fm.id)
            interior = interior_by_fm.get(fm_id, [])
            avg: float | None = (
                statistics.mean(ev.total_m3_ha for ev in interior)
                if len(interior) >= MIN_INTERIOR_EVENTS
                else None
            )
            sector_results.append(
                _SectorResult(
                    sector_id=str(sector.id),
                    sector_name=sector.name,
                    crop_type=sector.crop_type or "unknown",
                    interior_events=interior,
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
                        f"{sr.sector_name} tem apenas {len(sr.interior_events)} evento(s) "
                        f"interior(es) nos últimos {PERIOD_DAYS} dias. "
                        f"São necessários pelo menos {MIN_INTERIOR_EVENTS} para avaliação."
                    ),
                    description_en=(
                        f"{sr.sector_name} has only {len(sr.interior_events)} interior "
                        f"event(s) in the last {PERIOD_DAYS} days. "
                        f"At least {MIN_INTERIOR_EVENTS} are required for evaluation."
                    ),
                    farm_id=farm_id,
                    sector_id=sr.sector_id,
                    data={"interior_event_count": len(sr.interior_events), "period_days": PERIOD_DAYS},
                ))
                continue

            crop_avg = result.crop_averages.get(sr.crop_type)
            if not crop_avg:
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
                    f"{sr.sector_name} aplica em média {sr.interior_avg:.1f} m³/ha por evento — "
                    f"{abs(deviation_pct):.1f}% {direction_pt} da média da cultura "
                    f"({crop_avg:.1f} m³/ha)."
                ),
                description_en=(
                    f"{sr.sector_name} averages {sr.interior_avg:.1f} m³/ha per event — "
                    f"{abs(deviation_pct):.1f}% {direction} the crop average ({crop_avg:.1f} m³/ha)."
                ),
                farm_id=farm_id,
                sector_id=sr.sector_id,
                data={
                    "deviation_pct": round(deviation_pct, 1),
                    "direction": direction,
                    "sector_avg_m3ha": round(sr.interior_avg, 2),
                    "crop_avg_m3ha": round(crop_avg, 2),
                    "interior_event_count": len(sr.interior_events),
                    "period_days": PERIOD_DAYS,
                },
            ))
        return alerts

    async def _compute(self, farm_id: str, db: AsyncSession) -> _ComputeResult:
        from app.models import Flowmeter, IrrigationEventDetected, Plot, Sector
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
        ev_result = await db.execute(
            select(IrrigationEventDetected)
            .where(
                IrrigationEventDetected.flowmeter_id.in_(fm_ids),
                IrrigationEventDetected.start_time >= since,
            )
            .order_by(IrrigationEventDetected.start_time)
        )
        all_events = ev_result.scalars().all()
        return self._compute_from_data(pairs, all_events)
