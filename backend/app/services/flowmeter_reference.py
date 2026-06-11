"""Flowmeter reference flow rate service.

Pure computation functions + DB-backed service for establishing and managing
per-sector reference flow rates used for irrigation anomaly detection.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MIN_EVENTS_ESTABLISHED = 5
MIN_EVENTS_PROVISIONAL = 3


@dataclass
class StableRateResult:
    stable_rate_m3_ha: float | None
    std_dev: float
    num_readings_used: int
    status: str  # "ok", "too_short"


def compute_stable_flow_rate(
    readings: list[tuple[datetime, float]],
    trim_start: int = 2,
    trim_end: int = 2,
    min_readings: int = 3,
) -> StableRateResult:
    """Compute the stable flow rate from raw readings within one irrigation event.

    Sorts readings by timestamp, discards the first `trim_start` (ramp-up) and
    last `trim_end` (ramp-down), then returns the mean of what remains.
    Returns status="too_short" if fewer than `min_readings` remain after trimming.
    """
    if not readings:
        return StableRateResult(None, 0.0, 0, "too_short")
    sorted_r = sorted(readings, key=lambda t: t[0])
    end = len(sorted_r) - trim_end if trim_end > 0 else len(sorted_r)
    trimmed = sorted_r[trim_start:end]
    if len(trimmed) < min_readings:
        return StableRateResult(None, 0.0, len(trimmed), "too_short")
    values = [v for _, v in trimmed]
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return StableRateResult(round(mean, 4), round(std, 4), len(trimmed), "ok")


def compute_reference_from_stable_rates(
    stable_rates: list[float],
    tolerance_pct: float = 5.0,
) -> dict:
    """Compute a reference dict from a list of per-event stable rates.

    Returns a dict with keys:
        reference_rate_m3_ha: float | None
        upper_limit_m3_ha: float | None
        lower_limit_m3_ha: float | None
        std_dev: float
        num_events: int
        status: "established" | "provisional" | "insufficient"
    """
    n = len(stable_rates)
    if n < MIN_EVENTS_PROVISIONAL:
        return {
            "reference_rate_m3_ha": None,
            "upper_limit_m3_ha": None,
            "lower_limit_m3_ha": None,
            "std_dev": 0.0,
            "num_events": n,
            "status": "insufficient",
        }
    ref = statistics.median(stable_rates)
    std = statistics.stdev(stable_rates) if n > 1 else 0.0
    upper = round(ref * (1 + tolerance_pct / 100), 4)
    lower = round(ref * (1 - tolerance_pct / 100), 4)
    status = "established" if n >= MIN_EVENTS_ESTABLISHED else "provisional"
    return {
        "reference_rate_m3_ha": round(ref, 4),
        "upper_limit_m3_ha": upper,
        "lower_limit_m3_ha": lower,
        "std_dev": round(std, 4),
        "num_events": n,
        "status": status,
    }


class FlowmeterReferenceService:
    """Compute and persist per-flowmeter reference flow rates."""

    async def _load_events(
        self, flowmeter_id: str, since: datetime, db: AsyncSession
    ) -> list:
        from app.models import IrrigationEventDetected
        result = await db.execute(
            select(IrrigationEventDetected)
            .where(
                IrrigationEventDetected.flowmeter_id == flowmeter_id,
                IrrigationEventDetected.start_time >= since,
            )
            .order_by(IrrigationEventDetected.start_time)
        )
        return result.scalars().all()

    async def _load_readings_for_event(self, event, db: AsyncSession) -> list:
        from app.models import FlowmeterReading
        result = await db.execute(
            select(FlowmeterReading)
            .where(
                FlowmeterReading.flowmeter_id == event.flowmeter_id,
                FlowmeterReading.timestamp >= event.start_time,
                FlowmeterReading.timestamp <= event.end_time,
            )
            .order_by(FlowmeterReading.timestamp)
        )
        return result.scalars().all()

    async def compute_reference(
        self,
        flowmeter_id: str,
        sector_id: str,
        sector_name: str,
        db: AsyncSession,
        lookback_days: int = 30,
        tolerance_pct: float = 5.0,
    ) -> "FlowmeterReference":
        from app.models.flowmeter_reference import FlowmeterReference

        since = datetime.now(UTC) - timedelta(days=lookback_days)
        events = await self._load_events(flowmeter_id, since, db)

        stable_rates: list[float] = []
        for event in events:
            raw = await self._load_readings_for_event(event, db)
            reading_pairs = [(r.timestamp, r.value_m3_ha) for r in raw]
            result = compute_stable_flow_rate(reading_pairs)
            if result.status == "ok" and result.stable_rate_m3_ha is not None:
                stable_rates.append(result.stable_rate_m3_ha)

        ref_data = compute_reference_from_stable_rates(stable_rates, tolerance_pct=tolerance_pct)
        now = datetime.now(UTC)

        row = FlowmeterReference(
            flowmeter_id=flowmeter_id,
            reference_rate_m3_ha=ref_data["reference_rate_m3_ha"] or 0.0,
            tolerance_pct=tolerance_pct,
            upper_limit_m3_ha=ref_data["upper_limit_m3_ha"] or 0.0,
            lower_limit_m3_ha=ref_data["lower_limit_m3_ha"] or 0.0,
            num_events_analyzed=ref_data["num_events"],
            std_dev=ref_data["std_dev"],
            status=ref_data["status"],
            computed_at=now,
            is_manual_override=False,
        )
        return row

    async def compute_and_save(
        self,
        flowmeter_id: str,
        sector_id: str,
        sector_name: str,
        db: AsyncSession,
        lookback_days: int = 30,
        tolerance_pct: float = 5.0,
    ) -> "FlowmeterReference":
        """Compute reference and upsert into DB. Preserves is_manual_override rows.
        Caller is responsible for calling db.commit() after this method returns.
        """
        from app.models.flowmeter_reference import FlowmeterReference

        existing_result = await db.execute(
            select(FlowmeterReference).where(FlowmeterReference.flowmeter_id == flowmeter_id)
        )
        existing = existing_result.scalar_one_or_none()

        if existing and existing.is_manual_override:
            return existing

        row = await self.compute_reference(
            flowmeter_id, sector_id, sector_name, db,
            lookback_days=lookback_days,
            tolerance_pct=existing.tolerance_pct if existing else tolerance_pct,
        )

        if existing:
            existing.reference_rate_m3_ha = row.reference_rate_m3_ha
            existing.upper_limit_m3_ha = row.upper_limit_m3_ha
            existing.lower_limit_m3_ha = row.lower_limit_m3_ha
            existing.num_events_analyzed = row.num_events_analyzed
            existing.std_dev = row.std_dev
            existing.status = row.status
            existing.computed_at = row.computed_at
            return existing
        else:
            db.add(row)
            await db.flush()
            return row

    async def compute_all_for_farm(
        self,
        farm_id: str,
        db: AsyncSession,
        lookback_days: int = 30,
    ) -> list["FlowmeterReference"]:
        """Recompute references for all active flowmeters in a farm."""
        from app.models import Flowmeter, Plot, Sector

        result = await db.execute(
            select(Flowmeter, Sector)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .where(Plot.farm_id == farm_id, Flowmeter.is_active.is_(True))
        )
        pairs = result.all()
        refs: list = []
        for fm, sector in pairs:
            ref = await self.compute_and_save(
                flowmeter_id=str(fm.id),
                sector_id=str(sector.id),
                sector_name=sector.name,
                db=db,
                lookback_days=lookback_days,
            )
            refs.append(ref)
        return refs
