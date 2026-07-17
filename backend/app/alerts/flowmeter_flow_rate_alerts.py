# backend/app/alerts/flowmeter_flow_rate_alerts.py
"""Flowmeter flow-rate alert checker.

Detects per-event flow rate deviations vs the established reference rate,
and mid-event zero readings that indicate supply interruptions.

  _check_event_rate:
    Compares the stable flow rate of a single irrigation event against the
    per-sector FlowmeterReference. Returns a HIGH or LOW alert when the
    deviation exceeds reference.tolerance_pct, or None if within bounds.

  _detect_mid_event_zeros:
    Inspects raw readings within an event for interior zero values, which
    indicate valve closures or supply interruptions during irrigation.

  check_and_persist:
    Loads all active flowmeters with their reference for a farm, iterates
    over unprocessed events, generates alerts, and persists them to the DB.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertSeverity, AlertType
from app.models.alert import Alert
from app.utils.format_pt import fmt_pt

logger = logging.getLogger(__name__)


def _make_alert(
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
        source="flowmeter_flow_rate",
        rule_key=(
            f"{alert_type}:{sector_id}:"
            f"{data.get('event_start_time', 'unknown')}"
        ),
        title_pt=title_pt,
        title_en=title_en,
        description_pt=description_pt,
        description_en=description_en,
        farm_id=farm_id,
        sector_id=sector_id,
        is_active=True,
        data=data,
    )


class FlowmeterFlowRateAlertChecker:
    """Check for per-event flow rate anomalies using FlowmeterReference data."""

    def _check_event_rate(
        self,
        stable_rate: float,
        reference,
        sector_name: str,
        sector_id: str,
        farm_id: str,
        event_time: datetime,
    ) -> Alert | None:
        """Compare stable_rate against the reference band and return an alert or None.

        Returns None when reference.status == "insufficient" or the deviation is
        within the tolerance band.
        """
        if reference.status == "insufficient":
            return None

        ref_rate = reference.reference_rate_m3_ha
        if not ref_rate:
            return None
        deviation_pct = (stable_rate - ref_rate) / ref_rate * 100

        if abs(deviation_pct) <= reference.tolerance_pct:
            return None

        event_start_iso = event_time.isoformat()
        data = {
            "stable_rate_m3_ha": round(stable_rate, 4),
            "reference_rate_m3_ha": round(ref_rate, 4),
            "deviation_pct": round(deviation_pct, 2),
            "event_start_time": event_start_iso,
        }

        if deviation_pct > 0:
            return _make_alert(
                alert_type=AlertType.FLOWMETER_FLOW_RATE_HIGH,
                severity=AlertSeverity.WARNING,
                title_pt=f"Caudal elevado: {sector_name}",
                title_en=f"High flow rate: {sector_name}",
                description_pt=(
                    f"{sector_name}: caudal estável de {fmt_pt(stable_rate, 2)} m³/ha — "
                    f"{fmt_pt(deviation_pct)}% acima da referência ({fmt_pt(ref_rate, 2)} m³/ha)."
                ),
                description_en=(
                    f"{sector_name}: stable flow rate {stable_rate:.2f} m³/ha — "
                    f"{deviation_pct:.1f}% above reference ({ref_rate:.2f} m³/ha)."
                ),
                farm_id=farm_id,
                sector_id=sector_id,
                data=data,
            )
        else:
            return _make_alert(
                alert_type=AlertType.FLOWMETER_FLOW_RATE_LOW,
                severity=AlertSeverity.WARNING,
                title_pt=f"Caudal reduzido: {sector_name}",
                title_en=f"Low flow rate: {sector_name}",
                description_pt=(
                    f"{sector_name}: caudal estável de {fmt_pt(stable_rate, 2)} m³/ha — "
                    f"{fmt_pt(abs(deviation_pct))}% abaixo da referência ({fmt_pt(ref_rate, 2)} m³/ha)."
                ),
                description_en=(
                    f"{sector_name}: stable flow rate {stable_rate:.2f} m³/ha — "
                    f"{abs(deviation_pct):.1f}% below reference ({ref_rate:.2f} m³/ha)."
                ),
                farm_id=farm_id,
                sector_id=sector_id,
                data=data,
            )

    def _detect_mid_event_zeros(
        self,
        readings: list[tuple[datetime, float]],
        sector_name: str,
        sector_id: str,
        farm_id: str,
        event_time: datetime,
        zero_threshold: float = 0.1,
    ) -> Alert | None:
        """Detect zero readings in the interior of an irrigation event.

        Skips the first and last reading (ramp-up/ramp-down) and counts
        interior readings at or below zero_threshold. Returns None if none found.
        """
        sorted_r = sorted(readings, key=lambda t: t[0])
        interior = sorted_r[1:-1]
        zero_count = sum(1 for _, v in interior if v <= zero_threshold)

        if zero_count == 0:
            return None

        return _make_alert(
            alert_type=AlertType.FLOWMETER_MID_EVENT_ZEROS,
            severity=AlertSeverity.INFO,
            title_pt=f"Zeros durante rega: {sector_name}",
            title_en=f"Mid-event zeros: {sector_name}",
            description_pt=(
                f"{sector_name}: {zero_count} leitura(s) com valor zero durante a rega "
                f"em {event_time.isoformat()} — possível interrupção de fornecimento."
            ),
            description_en=(
                f"{sector_name}: {zero_count} zero reading(s) during irrigation "
                f"at {event_time.isoformat()} — possible supply interruption."
            ),
            farm_id=farm_id,
            sector_id=sector_id,
            data={
                "zero_count": zero_count,
                "event_start_time": event_time.isoformat(),
            },
        )

    async def check_and_persist(self, farm_id: str, db: AsyncSession) -> list[Alert]:
        """Load events, check flow rates and mid-event zeros, persist alerts.

        Only processes events since ref.last_alert_check_at (or last hour if None).
        Updates last_alert_check_at on each reference after processing.
        Returns the list of newly created Alert objects.
        """
        from app.models import Flowmeter, FlowmeterReading, IrrigationEventDetected, Plot, Sector
        from app.models.flowmeter_reference import FlowmeterReference
        from app.services.flowmeter_reference import compute_stable_flow_rate

        fm_result = await db.execute(
            select(Flowmeter, Sector, FlowmeterReference)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .outerjoin(FlowmeterReference, FlowmeterReference.flowmeter_id == Flowmeter.id)
            .where(
                Plot.farm_id == farm_id,
                Plot.is_archived.is_(False),
                Sector.is_archived.is_(False),
                Flowmeter.is_active.is_(True),
            )
        )
        rows = fm_result.all()

        new_alerts: list[Alert] = []

        for fm, sector, ref in rows:
            if ref is None or ref.status == "insufficient":
                continue

            since = ref.last_alert_check_at or (datetime.now(UTC) - timedelta(hours=1))

            events_result = await db.execute(
                select(IrrigationEventDetected)
                .where(
                    IrrigationEventDetected.flowmeter_id == str(fm.id),
                    IrrigationEventDetected.start_time > since,
                )
                .order_by(IrrigationEventDetected.start_time)
            )
            events = events_result.scalars().all()

            if not events:
                continue

            for event in events:
                readings_result = await db.execute(
                    select(FlowmeterReading)
                    .where(
                        FlowmeterReading.flowmeter_id == str(fm.id),
                        FlowmeterReading.timestamp >= event.start_time,
                        FlowmeterReading.timestamp <= event.end_time,
                    )
                    .order_by(FlowmeterReading.timestamp)
                )
                raw_readings = readings_result.scalars().all()
                reading_pairs = [(r.timestamp, r.value_m3_ha) for r in raw_readings]

                stable_result = compute_stable_flow_rate(reading_pairs)
                if stable_result.status == "ok" and stable_result.stable_rate_m3_ha is not None:
                    rate_alert = self._check_event_rate(
                        stable_result.stable_rate_m3_ha,
                        ref,
                        sector.name,
                        str(sector.id),
                        farm_id,
                        event.start_time,
                    )
                    if rate_alert is not None:
                        db.add(rate_alert)
                        new_alerts.append(rate_alert)

                zero_alert = None
                if reading_pairs:
                    zero_alert = self._detect_mid_event_zeros(
                        reading_pairs,
                        sector.name,
                        str(sector.id),
                        farm_id,
                        event.start_time,
                    )
                if zero_alert is not None:
                    db.add(zero_alert)
                    new_alerts.append(zero_alert)

            # Update checkpoint to the end time of the last processed event
            ref.last_alert_check_at = events[-1].end_time

        await db.commit()

        return new_alerts
