# backend/app/services/flowmeter_ingestion.py
"""Flowmeter data ingestion service.

Fetches Water Meter readings from the MyIrrigation API (same endpoint/auth as
probes, different device IDs) and detects irrigation events from the time-series.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event detection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectedEvent:
    start_time: datetime
    end_time: datetime
    duration_minutes: float
    total_m3_ha: float
    peak_m3_ha: float
    num_readings: int


class IrrigationEventDetector:
    """Detect irrigation events from flowmeter 15-minute time-series data."""

    def detect_events(
        self,
        readings: list[tuple[datetime, float]],
        threshold_m3_ha: float = 0.5,
    ) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        in_event = False
        event_readings: list[tuple[datetime, float]] = []

        for ts, value in sorted(readings, key=lambda x: x[0]):
            if value > threshold_m3_ha:
                in_event = True
                event_readings.append((ts, value))
            else:
                if in_event and event_readings:
                    if len(event_readings) >= 2:
                        events.append(self._build_event(event_readings))
                    in_event = False
                    event_readings = []

        # Close event still open at end of data
        if in_event and len(event_readings) >= 2:
            events.append(self._build_event(event_readings))

        return events

    def _build_event(self, readings: list[tuple[datetime, float]]) -> DetectedEvent:
        start_time = readings[0][0]
        end_time = readings[-1][0]
        duration_minutes = (end_time - start_time).total_seconds() / 60.0
        total_m3_ha = sum(v for _, v in readings)
        peak_m3_ha = max(v for _, v in readings)
        return DetectedEvent(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            total_m3_ha=round(total_m3_ha, 4),
            peak_m3_ha=peak_m3_ha,
            num_readings=len(readings),
        )


# ---------------------------------------------------------------------------
# Ingestion service
# ---------------------------------------------------------------------------

_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_MAX_ADAPTIVE_LOOKBACK_HOURS = 168


def _adaptive_since(last_ts: datetime | None, default_lookback_hours: int, now: datetime) -> datetime:
    default_since = now - timedelta(hours=default_lookback_hours)
    if last_ts is None:
        return default_since
    ts = last_ts if last_ts.tzinfo else last_ts.replace(tzinfo=UTC)
    if ts >= default_since:
        return default_since
    # Gap detected — extend lookback to cover since last reading
    extended = max(ts - timedelta(minutes=5), now - timedelta(hours=_MAX_ADAPTIVE_LOOKBACK_HOURS))
    logger.info(
        "FlowmeterIngestion: gap detected since %s, extending lookback to %s",
        ts.isoformat(), extended.isoformat(),
    )
    return extended


class FlowmeterIngestionService:
    """Fetch and store flowmeter readings + detect irrigation events."""

    async def ingest_farm(self, farm_id: str, db: AsyncSession) -> dict:
        """Run ingestion for all active flowmeters of a farm."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.adapters.factory import get_probe_provider
        from app.adapters.mock_probe import MockProbeProvider
        from app.adapters.myirrigation import MyIrrigationAdapter
        from app.config import get_settings
        from app.models import Farm, Flowmeter, Plot, Sector

        settings = get_settings()
        farm_result = await db.execute(
            select(Farm).where(Farm.id == farm_id).options(selectinload(Farm.credentials))
        )
        farm = farm_result.scalar_one_or_none()
        if farm is None:
            return {}

        adapter = get_probe_provider(settings, farm=farm)
        if isinstance(adapter, MockProbeProvider):
            logger.debug("FlowmeterIngestion: mock provider — skipping farm %s", farm_id)
            return {}

        if not isinstance(adapter, MyIrrigationAdapter):
            logger.warning("FlowmeterIngestion: unsupported adapter type %s", type(adapter))
            return {}

        # Load all active flowmeters for this farm
        flowmeters_result = await db.execute(
            select(Flowmeter)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .where(Plot.farm_id == farm_id, Flowmeter.is_active.is_(True))
        )
        flowmeters = flowmeters_result.scalars().all()
        if not flowmeters:
            return {}

        now = datetime.now(UTC)
        total_inserted = 0
        total_events = 0

        for flowmeter in flowmeters:
            since = _adaptive_since(flowmeter.last_reading_at, 2, now)
            try:
                inserted = await self.ingest_device(flowmeter, since, now, adapter, db)
                total_inserted += inserted
                if inserted > 0:
                    events_added = await self._detect_and_store_events(flowmeter, since, now, db)
                    total_events += events_added
            except Exception:
                logger.exception(
                    "FlowmeterIngestion: failed for device %s (flowmeter %s)",
                    flowmeter.external_device_id, flowmeter.id,
                )

        await db.commit()
        logger.info(
            "FlowmeterIngestion farm=%s: %d readings inserted, %d events detected",
            farm_id, total_inserted, total_events,
        )
        return {
            "flowmeters_processed": len(flowmeters),
            "readings_inserted": total_inserted,
            "events_detected": total_events,
        }

    async def ingest_device(
        self,
        flowmeter: Flowmeter,  # noqa: F821
        since: datetime,
        until: datetime,
        adapter: MyIrrigationAdapter,  # noqa: F821
        db: AsyncSession,
    ) -> int:
        """Fetch readings for one flowmeter and bulk-insert with deduplication."""
        import uuid

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.adapters.myirrigation import parse_flowmeter_data
        from app.models import FlowmeterReading

        # _post_form_json handles authentication internally (including token refresh)
        try:
            raw = await adapter._post_form_json(
                f"/data/devices/{flowmeter.external_device_id}/data",
                form_data={
                    "start_date": since.strftime(_DATE_FMT),
                    "end_date": until.strftime(_DATE_FMT),
                },
                params={"use_key_index": ""},
            )
        except Exception:
            logger.exception(
                "FlowmeterIngestion: API call failed for device %s", flowmeter.external_device_id
            )
            return 0

        readings = parse_flowmeter_data(raw, flowmeter.external_device_id)
        if not readings:
            return 0

        rows = [
            {
                "id": str(uuid.uuid4()),
                "flowmeter_id": flowmeter.id,
                "timestamp": ts,
                "value_m3_ha": value,
            }
            for ts, value in readings
        ]

        stmt = (
            pg_insert(FlowmeterReading)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_flowmeter_reading_device_ts")
        )
        result = await db.execute(stmt)
        inserted = result.rowcount if result.rowcount >= 0 else len(rows)

        # Always advance last_reading_at when the API returned data,
        # regardless of how many rows were actually inserted vs. deduplicated.
        # asyncpg returns -1 for rowcount on mixed ON CONFLICT batches.
        latest_ts = max(ts for ts, _ in readings)
        flowmeter.last_reading_at = latest_ts

        logger.debug(
            "FlowmeterIngestion device %s: %d/%d readings inserted",
            flowmeter.external_device_id, inserted, len(rows),
        )
        return inserted

    async def _detect_and_store_events(
        self,
        flowmeter: Flowmeter,  # noqa: F821
        since: datetime,
        until: datetime,
        db: AsyncSession,
    ) -> int:
        """Run event detection over the current window and upsert results."""
        import uuid

        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models import FlowmeterReading, IrrigationEventDetected

        # Load readings for this window
        rows_result = await db.execute(
            select(FlowmeterReading)
            .where(
                FlowmeterReading.flowmeter_id == flowmeter.id,
                FlowmeterReading.timestamp >= since,
                FlowmeterReading.timestamp <= until,
            )
            .order_by(FlowmeterReading.timestamp)
        )
        raw_readings = [(r.timestamp, r.value_m3_ha) for r in rows_result.scalars().all()]
        if not raw_readings:
            return 0

        detector = IrrigationEventDetector()
        events = detector.detect_events(raw_readings)

        added = 0
        for ev in events:
            stmt = (
                pg_insert(IrrigationEventDetected)
                .values(
                    id=str(uuid.uuid4()),
                    flowmeter_id=flowmeter.id,
                    sector_id=flowmeter.sector_id,
                    start_time=ev.start_time,
                    end_time=ev.end_time,
                    duration_minutes=ev.duration_minutes,
                    total_m3_ha=ev.total_m3_ha,
                    peak_m3_ha=ev.peak_m3_ha,
                    num_readings=ev.num_readings,
                    date=ev.start_time.date(),
                )
                .on_conflict_do_nothing(
                    constraint="uq_irrigation_event_detected_device_start"
                )
            )
            result = await db.execute(stmt)
            added += result.rowcount if result.rowcount >= 0 else 1

        return added
