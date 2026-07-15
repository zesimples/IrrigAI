"""Flowmeter irrigation-dose deviation checker.

The checker compares a sector's typical irrigation dose with comparable sectors
of the same crop. It uses detected irrigation events rather than raw meter
readings, so an irrigation crossing midnight is counted once and no artificial
first/last-reading trimming is needed.

For each sector, the typical dose is the median ``total_m3_ha`` of its events
in the selected period. Its baseline is the leave-one-out median of the other
evaluated sectors of the same crop. At least two events and two peers are
required before a deviation is reported.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertSeverity, AlertType
from app.models.alert import Alert

logger = logging.getLogger(__name__)

DEFAULT_PERIOD = "7d"
MIN_EVENTS = 2
MIN_PEER_SECTORS = 2
INFO_DEVIATION_THRESHOLD_PCT = 5.0
WARNING_DEVIATION_THRESHOLD_PCT = 15.0

DeviationPeriod = Literal["7d", "30d", "season"]
DeviationStatus = Literal[
    "normal",
    "info",
    "warning",
    "insufficient_data",
    "insufficient_peer_data",
]


@dataclass
class _SectorResult:
    sector_id: str
    sector_name: str
    crop_type: str
    event_doses: list[float]
    typical_dose: float | None


@dataclass
class _SectorDeviation:
    sector: _SectorResult
    status: DeviationStatus
    peer_sector_count: int
    crop_baseline: float | None = None
    deviation_pct: float | None = None
    absolute_delta_m3ha: float | None = None


@dataclass
class _ComputeResult:
    sector_results: list[_SectorResult]
    crop_averages: dict[str, float]
    period_days: int


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
        source="flowmeter_deviation",
        rule_key=f"{alert_type}:{sector_id}",
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
    """Check typical irrigation-dose deviations against same-crop peers."""

    async def check(self, farm_id: str, db: AsyncSession) -> list[Alert]:
        """Compute the default 7-day deviations and return Alert objects.

        This method is used by the scheduled alert engine. It does not write to
        the database itself.
        """
        result = await self._compute(farm_id, db, DEFAULT_PERIOD)
        return self._build_alerts(result, farm_id)

    async def compute_deviations(
        self,
        farm_id: str,
        db: AsyncSession,
        period: DeviationPeriod = DEFAULT_PERIOD,
    ):
        """Return all sector deviation states for the selected dashboard period."""
        from app.schemas.flowmeter import (
            FlowmeterDeviationSector,
            FlowmeterDeviationsResponse,
            FlowmeterInsufficientDataSector,
        )

        result = await self._compute(farm_id, db, period)
        evaluations = self._evaluate_sectors(result)
        sectors = [
            self._as_schema(evaluation, FlowmeterDeviationSector) for evaluation in evaluations
        ]
        deviating = [sector for sector in sectors if sector.status in {"info", "warning"}]
        insufficient_data = [
            FlowmeterInsufficientDataSector(
                sector_id=evaluation.sector.sector_id,
                sector_name=evaluation.sector.sector_name,
                crop_type=evaluation.sector.crop_type,
                event_count=len(evaluation.sector.event_doses),
                reason=(
                    "insufficient_events"
                    if evaluation.status == "insufficient_data"
                    else "insufficient_peers"
                ),
            )
            for evaluation in evaluations
            if evaluation.status in {"insufficient_data", "insufficient_peer_data"}
        ]

        return FlowmeterDeviationsResponse(
            period_days=result.period_days,
            sectors=sectors,
            deviating=deviating,
            insufficient_data=insufficient_data,
            crop_averages={k: round(v, 2) for k, v in result.crop_averages.items()},
            evaluated_at=datetime.now(UTC),
        )

    @staticmethod
    def _as_schema(evaluation: _SectorDeviation, schema_type):
        sector = evaluation.sector
        direction: Literal["above", "below"] | None = None
        if evaluation.deviation_pct is not None and evaluation.deviation_pct != 0:
            direction = "above" if evaluation.deviation_pct > 0 else "below"
        return schema_type(
            sector_id=sector.sector_id,
            sector_name=sector.sector_name,
            crop_type=sector.crop_type,
            status=evaluation.status,
            direction=direction,
            deviation_pct=(
                round(evaluation.deviation_pct, 1) if evaluation.deviation_pct is not None else None
            ),
            absolute_delta_m3ha=(
                round(evaluation.absolute_delta_m3ha, 2)
                if evaluation.absolute_delta_m3ha is not None
                else None
            ),
            sector_avg_m3ha=(
                round(sector.typical_dose, 2) if sector.typical_dose is not None else None
            ),
            crop_avg_m3ha=(
                round(evaluation.crop_baseline, 2) if evaluation.crop_baseline is not None else None
            ),
            event_count=len(sector.event_doses),
            peer_sector_count=evaluation.peer_sector_count,
        )

    def _compute_from_events(
        self,
        pairs: list,
        events: list,
        period_days: int = 7,
    ) -> _ComputeResult:
        """Compute sector dose medians from pre-loaded detected events.

        Kept independent of the database for deterministic regression tests.
        """
        event_doses_by_fm: dict[str, list[float]] = defaultdict(list)
        for event in events:
            if event.total_m3_ha > 0:
                event_doses_by_fm[str(event.flowmeter_id)].append(event.total_m3_ha)

        sector_results: list[_SectorResult] = []
        for flowmeter, sector in pairs:
            event_doses = event_doses_by_fm.get(str(flowmeter.id), [])
            typical_dose = (
                statistics.median(event_doses) if len(event_doses) >= MIN_EVENTS else None
            )
            sector_results.append(
                _SectorResult(
                    sector_id=str(sector.id),
                    sector_name=sector.name,
                    crop_type=sector.crop_type or "unknown",
                    event_doses=event_doses,
                    typical_dose=typical_dose,
                )
            )

        crop_values: dict[str, list[float]] = defaultdict(list)
        for sector in sector_results:
            if sector.typical_dose is not None:
                crop_values[sector.crop_type].append(sector.typical_dose)

        return _ComputeResult(
            sector_results=sector_results,
            crop_averages={
                crop: statistics.median(values) for crop, values in crop_values.items() if values
            },
            period_days=period_days,
        )

    def _evaluate_sectors(self, result: _ComputeResult) -> list[_SectorDeviation]:
        """Build leave-one-out peer baselines and severity states."""
        evaluated_by_crop: dict[str, list[_SectorResult]] = defaultdict(list)
        for sector in result.sector_results:
            if sector.typical_dose is not None:
                evaluated_by_crop[sector.crop_type].append(sector)

        evaluations: list[_SectorDeviation] = []
        for sector in result.sector_results:
            if sector.typical_dose is None:
                evaluations.append(
                    _SectorDeviation(
                        sector=sector,
                        status="insufficient_data",
                        peer_sector_count=0,
                    )
                )
                continue

            peers = [
                peer.typical_dose
                for peer in evaluated_by_crop[sector.crop_type]
                if peer.sector_id != sector.sector_id and peer.typical_dose is not None
            ]
            if len(peers) < MIN_PEER_SECTORS:
                evaluations.append(
                    _SectorDeviation(
                        sector=sector,
                        status="insufficient_peer_data",
                        peer_sector_count=len(peers),
                    )
                )
                continue

            baseline = statistics.median(peers)
            if baseline <= 0:
                logger.warning(
                    "Skipping deviation for sector %s because crop baseline is non-positive",
                    sector.sector_id,
                )
                evaluations.append(
                    _SectorDeviation(
                        sector=sector,
                        status="insufficient_peer_data",
                        peer_sector_count=len(peers),
                    )
                )
                continue

            absolute_delta = sector.typical_dose - baseline
            deviation_pct = absolute_delta / baseline * 100
            magnitude = abs(deviation_pct)
            status: DeviationStatus
            if magnitude <= INFO_DEVIATION_THRESHOLD_PCT:
                status = "normal"
            elif magnitude <= WARNING_DEVIATION_THRESHOLD_PCT:
                status = "info"
            else:
                status = "warning"

            evaluations.append(
                _SectorDeviation(
                    sector=sector,
                    status=status,
                    peer_sector_count=len(peers),
                    crop_baseline=baseline,
                    deviation_pct=deviation_pct,
                    absolute_delta_m3ha=absolute_delta,
                )
            )
        return evaluations

    def _build_alerts(self, result: _ComputeResult, farm_id: str) -> list[Alert]:
        alerts: list[Alert] = []
        for evaluation in self._evaluate_sectors(result):
            sector = evaluation.sector
            if evaluation.status == "insufficient_data":
                alerts.append(
                    _alert(
                        alert_type=AlertType.FLOWMETER_INSUFFICIENT_DATA,
                        severity=AlertSeverity.INFO,
                        title_pt=f"Dados insuficientes: {sector.sector_name}",
                        title_en=f"Insufficient data: {sector.sector_name}",
                        description_pt=(
                            f"{sector.sector_name} tem apenas {len(sector.event_doses)} rega(s) "
                            f"detetada(s) nos últimos {result.period_days} dias. "
                            f"São necessárias pelo menos {MIN_EVENTS} para avaliar a dotação."
                        ),
                        description_en=(
                            f"{sector.sector_name} has only {len(sector.event_doses)} detected "
                            f"irrigation event(s) in the last {result.period_days} days. "
                            f"At least {MIN_EVENTS} are required to evaluate the dose."
                        ),
                        farm_id=farm_id,
                        sector_id=sector.sector_id,
                        data={
                            "event_count": len(sector.event_doses),
                            "period_days": result.period_days,
                            "reason": "insufficient_events",
                        },
                    )
                )
                continue

            if evaluation.status == "insufficient_peer_data":
                alerts.append(
                    _alert(
                        alert_type=AlertType.FLOWMETER_INSUFFICIENT_DATA,
                        severity=AlertSeverity.INFO,
                        title_pt=f"Comparação indisponível: {sector.sector_name}",
                        title_en=f"Comparison unavailable: {sector.sector_name}",
                        description_pt=(
                            f"{sector.sector_name} não tem pelo menos {MIN_PEER_SECTORS} sectores "
                            "comparáveis da mesma cultura com dados suficientes."
                        ),
                        description_en=(
                            f"{sector.sector_name} does not have at least {MIN_PEER_SECTORS} "
                            "same-crop peer sectors with sufficient data."
                        ),
                        farm_id=farm_id,
                        sector_id=sector.sector_id,
                        data={
                            "event_count": len(sector.event_doses),
                            "peer_sector_count": evaluation.peer_sector_count,
                            "period_days": result.period_days,
                            "reason": "insufficient_peers",
                        },
                    )
                )
                continue

            if evaluation.status == "normal":
                continue

            assert evaluation.deviation_pct is not None
            assert evaluation.crop_baseline is not None
            assert evaluation.absolute_delta_m3ha is not None
            direction = "above" if evaluation.deviation_pct > 0 else "below"
            direction_pt = "acima" if direction == "above" else "abaixo"
            severity = AlertSeverity.INFO if evaluation.status == "info" else AlertSeverity.WARNING
            alerts.append(
                _alert(
                    alert_type=AlertType.FLOWMETER_DEVIATION,
                    severity=severity,
                    title_pt=f"Desvio de dotação: {sector.sector_name}",
                    title_en=f"Irrigation-dose deviation: {sector.sector_name}",
                    description_pt=(
                        f"{sector.sector_name} aplica tipicamente {sector.typical_dose:.1f} m³/ha "
                        f"por rega, {abs(evaluation.deviation_pct):.1f}% {direction_pt} da mediana "
                        f"dos sectores comparáveis ({evaluation.crop_baseline:.1f} m³/ha; "
                        f"diferença de {abs(evaluation.absolute_delta_m3ha):.1f} m³/ha)."
                    ),
                    description_en=(
                        f"{sector.sector_name} typically applies {sector.typical_dose:.1f} m³/ha "
                        f"per irrigation, {abs(evaluation.deviation_pct):.1f}% {direction} the peer "
                        f"median ({evaluation.crop_baseline:.1f} m³/ha; "
                        f"difference {abs(evaluation.absolute_delta_m3ha):.1f} m³/ha)."
                    ),
                    farm_id=farm_id,
                    sector_id=sector.sector_id,
                    data={
                        "deviation_pct": round(evaluation.deviation_pct, 1),
                        "absolute_delta_m3ha": round(evaluation.absolute_delta_m3ha, 2),
                        "direction": direction,
                        "sector_avg_m3ha": round(sector.typical_dose, 2),
                        "crop_avg_m3ha": round(evaluation.crop_baseline, 2),
                        "event_count": len(sector.event_doses),
                        "peer_sector_count": evaluation.peer_sector_count,
                        "period_days": result.period_days,
                        "status": evaluation.status,
                    },
                )
            )
        return alerts

    async def _compute(
        self,
        farm_id: str,
        db: AsyncSession,
        period: DeviationPeriod,
    ) -> _ComputeResult:
        from app.models import Flowmeter, IrrigationEventDetected, Plot, Sector

        now = datetime.now(UTC)
        if period == "season":
            first_event_result = await db.execute(
                select(sql_func.min(IrrigationEventDetected.start_time))
                .join(Flowmeter, IrrigationEventDetected.flowmeter_id == Flowmeter.id)
                .join(Sector, Flowmeter.sector_id == Sector.id)
                .join(Plot, Sector.plot_id == Plot.id)
                .where(
                    Plot.farm_id == farm_id,
                    Plot.is_archived.is_(False),
                    Sector.is_archived.is_(False),
                    Flowmeter.is_active.is_(True),
                )
            )
            since = first_event_result.scalar_one_or_none() or (now - timedelta(days=365))
        else:
            since = now - timedelta(days=7 if period == "7d" else 30)

        period_days = max(1, (now.date() - since.date()).days)
        flowmeters_result = await db.execute(
            select(Flowmeter, Sector)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .where(
                Plot.farm_id == farm_id,
                Plot.is_archived.is_(False),
                Sector.is_archived.is_(False),
                Flowmeter.is_active.is_(True),
            )
        )
        pairs = flowmeters_result.all()
        if not pairs:
            return _ComputeResult(sector_results=[], crop_averages={}, period_days=period_days)

        flowmeter_ids = [flowmeter.id for flowmeter, _ in pairs]
        events_result = await db.execute(
            select(IrrigationEventDetected)
            .where(
                IrrigationEventDetected.flowmeter_id.in_(flowmeter_ids),
                IrrigationEventDetected.start_time >= since,
                IrrigationEventDetected.start_time <= now,
            )
            .order_by(IrrigationEventDetected.start_time)
        )
        return self._compute_from_events(
            pairs,
            events_result.scalars().all(),
            period_days=period_days,
        )
