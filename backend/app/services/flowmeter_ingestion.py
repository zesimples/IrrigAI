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


def classify_flowmeter_run(readings_inserted: int, devices_failed: int) -> str:
    """Scheduler-metric status for one flowmeter ingestion run.

    Returns ``"failure"`` only when devices failed *and* nothing was ingested —
    the silent all-406 case that previously logged ``"success"`` and hid a
    multi-day outage. A run that ingested anything (or had no devices to process)
    is ``"success"``; per-device failures are surfaced separately on the
    flowmeter_device_ingestion_total metric so alerting can catch partial loss.
    """
    if devices_failed > 0 and readings_inserted == 0:
        return "failure"
    return "success"


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


# ---------------------------------------------------------------------------
# Event detection constants
# ---------------------------------------------------------------------------

#: Default reading interval when it cannot be inferred from the data.
_DEFAULT_INTERVAL_MINUTES: float = 15.0

#: Split an event when the gap between two consecutive positive readings
#: exceeds this multiple of the inferred interval.
#: 5.0 × 15 min = 75 min — prevents drip-system cycling pauses from
#: fragmenting a single irrigation session into multiple events.
_GAP_SPLIT_FACTOR: float = 5.0


def _infer_interval_minutes(readings: list[tuple[datetime, float]]) -> float:
    """Infer the median reading interval from sorted (timestamp, value) pairs.

    Returns _DEFAULT_INTERVAL_MINUTES if fewer than 2 readings or inference fails.
    """
    if len(readings) < 2:
        return _DEFAULT_INTERVAL_MINUTES
    gaps = [
        (readings[i + 1][0] - readings[i][0]).total_seconds() / 60
        for i in range(len(readings) - 1)
        if (readings[i + 1][0] - readings[i][0]).total_seconds() > 0
    ]
    if not gaps:
        return _DEFAULT_INTERVAL_MINUTES
    gaps.sort()
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 == 1 else (gaps[mid - 1] + gaps[mid]) / 2


class IrrigationEventDetector:
    """Detect irrigation events from flowmeter time-series data.

    Duration correction: each bucket covers one interval period, so the last
    bucket's interval is added to (end_time - start_time).

    Gap splitting: if consecutive positive readings are separated by more than
    _GAP_SPLIT_FACTOR × inferred_interval, they belong to different events.
    """

    def detect_events(
        self,
        readings: list[tuple[datetime, float]],
        threshold_m3_ha: float = 0.5,
    ) -> list[DetectedEvent]:
        sorted_readings = sorted(readings, key=lambda x: x[0])
        interval_minutes = _infer_interval_minutes(sorted_readings)
        gap_threshold_minutes = interval_minutes * _GAP_SPLIT_FACTOR

        events: list[DetectedEvent] = []
        current_segment: list[tuple[datetime, float]] = []

        for ts, value in sorted_readings:
            if value > threshold_m3_ha:
                if current_segment:
                    last_ts = current_segment[-1][0]
                    gap_minutes = (ts - last_ts).total_seconds() / 60
                    if gap_minutes > gap_threshold_minutes:
                        if len(current_segment) >= 2:
                            events.append(self._build_event(current_segment, interval_minutes))
                        current_segment = []
                current_segment.append((ts, value))
            else:
                if current_segment:
                    if len(current_segment) >= 2:
                        events.append(self._build_event(current_segment, interval_minutes))
                    current_segment = []

        if len(current_segment) >= 2:
            events.append(self._build_event(current_segment, interval_minutes))

        return events

    def _build_event(
        self,
        readings: list[tuple[datetime, float]],
        interval_minutes: float,
    ) -> DetectedEvent:
        start_time = readings[0][0]
        end_time = readings[-1][0]
        duration_minutes = (end_time - start_time).total_seconds() / 60.0 + interval_minutes
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
# How far back from the earliest new reading to extend the detection window.
_EVENT_DETECTION_LOOKBACK_HOURS = 24


def _flowmeter_sensor_summary(raw: object) -> list[dict[str, object]]:
    """Return safe sensor metadata for diagnosing failed flowmeter parsing."""
    if not isinstance(raw, dict):
        return []

    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    if not isinstance(data, dict):
        return []

    sensors = data.get("sensors")
    values_map = data.get("values")
    if not isinstance(sensors, list):
        return []
    if not isinstance(values_map, dict):
        values_map = {}

    summary: list[dict[str, object]] = []
    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue
        sensor_id = str(sensor.get("id") or "")
        sensor_values = values_map.get(sensor_id)
        summary.append(
            {
                "id": sensor_id,
                "name": str(sensor.get("name") or ""),
                "sensor_type": str(sensor.get("sensor_type") or ""),
                "units": str(sensor.get("units") or ""),
                "values": len(sensor_values) if isinstance(sensor_values, dict) else 0,
            }
        )
    return summary


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
            select(Farm).where(
                Farm.id == farm_id,
                Farm.is_archived.is_(False),
            ).options(selectinload(Farm.credentials))
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
        devices_succeeded = 0
        devices_failed = 0

        for flowmeter in flowmeters:
            since = _adaptive_since(flowmeter.last_reading_at, 2, now)
            try:
                inserted, earliest_ts, latest_ts = await self.ingest_device(
                    flowmeter, since, now, adapter, db
                )
                total_inserted += inserted
                # Run detection whenever the API returned readings — the bounded window and
                # ON CONFLICT DO NOTHING make this idempotent against duplicates.
                if earliest_ts is not None and latest_ts is not None:
                    events_added = await self._detect_and_store_events(
                        flowmeter, earliest_ts, latest_ts, db
                    )
                    total_events += events_added
                devices_succeeded += 1
            except Exception:
                # ingest_device already logged the traceback; just count it here so
                # the run reports the failure instead of silently reporting success.
                devices_failed += 1

        await db.commit()
        logger.info(
            "FlowmeterIngestion farm=%s: %d readings inserted, %d events detected, "
            "%d/%d devices ok",
            farm_id, total_inserted, total_events, devices_succeeded, len(flowmeters),
        )
        if devices_failed:
            logger.warning(
                "FlowmeterIngestion farm=%s: %d/%d device(s) failed",
                farm_id, devices_failed, len(flowmeters),
            )
        return {
            "flowmeters_processed": len(flowmeters),
            "readings_inserted": total_inserted,
            "events_detected": total_events,
            "devices_succeeded": devices_succeeded,
            "devices_failed": devices_failed,
        }

    async def ingest_device(
        self,
        flowmeter: Flowmeter,  # noqa: F821
        since: datetime,
        until: datetime,
        adapter: MyIrrigationAdapter,  # noqa: F821
        db: AsyncSession,
    ) -> tuple[int, datetime | None, datetime | None]:
        """Fetch readings for one flowmeter and bulk-insert with deduplication.

        Returns (inserted_count, earliest_timestamp, latest_timestamp).
        earliest/latest are from the API response and bound the detection window.
        """
        import uuid

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.adapters.myirrigation import parse_flowmeter_data
        from app.models import FlowmeterReading

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
            # Re-raise so the caller (ingest_farm) counts this as a failed device.
            # Previously this returned (0, None, None), making an all-failed run
            # (e.g. 406 on every device) indistinguishable from "no new data" and
            # letting the scheduler record the run as a success.
            logger.exception(
                "FlowmeterIngestion: API call failed for device %s (%s..%s)",
                flowmeter.external_device_id,
                since.isoformat(),
                until.isoformat(),
            )
            raise

        readings = parse_flowmeter_data(raw, flowmeter.external_device_id)
        if not readings:
            logger.warning(
                "FlowmeterIngestion device %s: no Water Meter readings parsed "
                "for window %s..%s; sensors=%s",
                flowmeter.external_device_id,
                since.isoformat(),
                until.isoformat(),
                _flowmeter_sensor_summary(raw),
            )
            return 0, None, None

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

        latest_ts = max(ts for ts, _ in readings)
        earliest_ts = min(ts for ts, _ in readings)
        flowmeter.last_reading_at = latest_ts

        logger.info(
            "FlowmeterIngestion device %s: %d/%d readings inserted (%s..%s)",
            flowmeter.external_device_id,
            inserted,
            len(rows),
            earliest_ts.isoformat(),
            latest_ts.isoformat(),
        )
        return inserted, earliest_ts, latest_ts

    async def _detect_and_store_events(
        self,
        flowmeter: Flowmeter,  # noqa: F821
        earliest_new_ts: datetime,
        latest_new_ts: datetime,
        db: AsyncSession,
    ) -> int:
        """Run event detection over a bounded window around new data.

        Scans [earliest_new_ts - 24h, latest_new_ts + 1h] so that:
        - Events that started before the ingestion window are captured.
        - The +1h buffer ensures the tail of the last event is included.
        ON CONFLICT DO NOTHING keeps this idempotent.
        """
        import uuid

        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models import FlowmeterReading, IrrigationEventDetected

        window_since = earliest_new_ts - timedelta(hours=_EVENT_DETECTION_LOOKBACK_HOURS)
        window_until = latest_new_ts + timedelta(hours=1)

        rows_result = await db.execute(
            select(FlowmeterReading)
            .where(
                FlowmeterReading.flowmeter_id == flowmeter.id,
                FlowmeterReading.timestamp >= window_since,
                FlowmeterReading.timestamp <= window_until,
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

    async def redetect_events(
        self,
        flowmeter: Flowmeter,  # noqa: F821
        window_since: datetime,
        window_until: datetime,
        db: AsyncSession,
    ) -> tuple[int, int]:
        """Delete existing events in a window then re-detect from raw readings.

        Use after changing detection parameters (e.g. _GAP_SPLIT_FACTOR) to
        replace stale fragmented events with freshly segmented ones.

        Returns (deleted_count, inserted_count).
        """
        import uuid

        from sqlalchemy import delete, select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models import FlowmeterReading, IrrigationEventDetected

        del_result = await db.execute(
            delete(IrrigationEventDetected).where(
                IrrigationEventDetected.flowmeter_id == str(flowmeter.id),
                IrrigationEventDetected.start_time >= window_since,
                IrrigationEventDetected.start_time <= window_until,
            )
        )
        deleted = del_result.rowcount if del_result.rowcount >= 0 else 0

        rows_result = await db.execute(
            select(FlowmeterReading)
            .where(
                FlowmeterReading.flowmeter_id == str(flowmeter.id),
                FlowmeterReading.timestamp >= window_since,
                FlowmeterReading.timestamp <= window_until,
            )
            .order_by(FlowmeterReading.timestamp)
        )
        raw_readings = [(r.timestamp, r.value_m3_ha) for r in rows_result.scalars().all()]
        if not raw_readings:
            return deleted, 0

        detector = IrrigationEventDetector()
        events = detector.detect_events(raw_readings)

        added = 0
        for ev in events:
            stmt = (
                pg_insert(IrrigationEventDetected)
                .values(
                    id=str(uuid.uuid4()),
                    flowmeter_id=str(flowmeter.id),
                    sector_id=flowmeter.sector_id,
                    start_time=ev.start_time,
                    end_time=ev.end_time,
                    duration_minutes=ev.duration_minutes,
                    total_m3_ha=ev.total_m3_ha,
                    peak_m3_ha=ev.peak_m3_ha,
                    num_readings=ev.num_readings,
                    date=ev.start_time.date(),
                )
                .on_conflict_do_nothing(constraint="uq_irrigation_event_detected_device_start")
            )
            result = await db.execute(stmt)
            added += result.rowcount if result.rowcount >= 0 else 1

        logger.info(
            "redetect_events device=%s window=%s..%s: deleted=%d inserted=%d",
            flowmeter.external_device_id,
            window_since.isoformat(),
            window_until.isoformat(),
            deleted,
            added,
        )
        return deleted, added

    async def backfill_events(self, flowmeter_id: str, db: AsyncSession) -> int:
        """Reprocess ALL historical readings for a flowmeter. One-off tool, not called by ingest_farm.

        Use this after migrating data or fixing the event detector logic.
        """
        import uuid

        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models import Flowmeter, FlowmeterReading, IrrigationEventDetected

        flowmeter_result = await db.execute(
            select(Flowmeter).where(Flowmeter.id == flowmeter_id)
        )
        flowmeter = flowmeter_result.scalar_one_or_none()
        if flowmeter is None:
            raise ValueError(f"Flowmeter {flowmeter_id} not found")

        rows_result = await db.execute(
            select(FlowmeterReading)
            .where(FlowmeterReading.flowmeter_id == flowmeter_id)
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
                .on_conflict_do_nothing(constraint="uq_irrigation_event_detected_device_start")
            )
            result = await db.execute(stmt)
            added += result.rowcount if result.rowcount >= 0 else 1

        await db.commit()
        logger.info("backfill_events flowmeter=%s: %d events upserted", flowmeter_id, added)
        return added
