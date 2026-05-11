"""Persistence layer for probe-derived water events.

The engine in `app.engine.water_event_detector` is stateless — given a probe's
readings it returns scored `ProbeDetectedEvent` objects.  This service runs the
detector and upserts the results into `detected_water_event` so downstream
consumers (LLM, agronomist UI, dashboards) can read previous detections,
attach confirmations/rejections, and avoid recomputing on every request.

Upserts are keyed by (probe_id, timestamp, kind) — re-running detection over an
overlapping window is idempotent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.water_event_detector import detect_water_events
from app.models import (
    DetectedWaterEvent,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Sector,
)
from app.schemas.probe import (
    DepthReadings,
    ProbeDetectedEvent,
    TimeSeriesPoint,
)

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7


async def _load_readings_window(
    db: AsyncSession,
    probe: Probe,
    since: datetime,
    until: datetime,
) -> list[DepthReadings]:
    """Load VWC readings grouped by depth for the detector."""
    depths = (
        await db.execute(
            select(ProbeDepth).where(
                ProbeDepth.probe_id == probe.id,
                ProbeDepth.sensor_type == "soil_moisture",
            )
        )
    ).scalars().all()

    result: list[DepthReadings] = []
    for depth in sorted(depths, key=lambda d: d.depth_cm):
        rows = (
            await db.execute(
                select(ProbeReading)
                .where(
                    ProbeReading.probe_depth_id == depth.id,
                    ProbeReading.timestamp >= since,
                    ProbeReading.timestamp <= until,
                    ProbeReading.unit == "vwc_m3m3",
                )
                .order_by(ProbeReading.timestamp)
            )
        ).scalars().all()
        points = [
            TimeSeriesPoint(
                timestamp=r.timestamp,
                vwc=r.calibrated_value if r.calibrated_value is not None else r.raw_value,
                quality=r.quality_flag,
            )
            for r in rows
        ]
        result.append(DepthReadings(depth_cm=depth.depth_cm, readings=points))
    return result


async def detect_and_persist_water_events(
    probe_id: str,
    db: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[DetectedWaterEvent]:
    """Run the water-event detector for a probe and upsert results.

    Returns the persisted DetectedWaterEvent ORM rows (existing + new).  Caller
    is responsible for committing the session.
    """
    now = datetime.now(UTC)
    since = since or (now - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    until = until or now

    probe = await db.get(Probe, probe_id)
    if probe is None:
        return []

    sector = await db.get(Sector, probe.sector_id)
    plot = await db.get(Plot, sector.plot_id) if sector else None
    farm_id = plot.farm_id if plot else None

    depths = await _load_readings_window(db, probe, since, until)
    if not depths:
        return []

    detected: list[ProbeDetectedEvent] = await detect_water_events(
        db=db,
        sector=sector,
        plot=plot,
        depths=depths,
        since=since,
        until=until,
    )

    persisted: list[DetectedWaterEvent] = []
    for event in detected:
        # Look up existing row by natural key (probe_id, timestamp, kind)
        existing = (
            await db.execute(
                select(DetectedWaterEvent).where(
                    DetectedWaterEvent.probe_id == probe.id,
                    DetectedWaterEvent.timestamp == event.timestamp,
                    DetectedWaterEvent.kind == event.kind,
                )
            )
        ).scalar_one_or_none()

        depths_cm = list(event.depths_cm)

        if existing is not None:
            # Refresh scores only; preserve confirm/reject state.
            existing.confidence = event.confidence
            existing.score = event.score
            existing.probability_irrigation = event.probability_irrigation
            existing.probability_rain = event.probability_rain
            existing.probability_unlogged = event.probability_unlogged
            existing.source_match_score = event.source_match_score
            existing.depth_sequence_score = event.depth_sequence_score
            existing.signal_strength_score = event.signal_strength_score
            existing.sensor_quality_score = event.sensor_quality_score
            existing.depths_cm = depths_cm
            existing.delta_vwc = event.delta_vwc
            existing.rainfall_mm = event.rainfall_mm
            existing.irrigation_mm = event.irrigation_mm
            existing.message = event.message
            persisted.append(existing)
            continue

        row = DetectedWaterEvent(
            id=str(uuid.uuid4()),
            probe_id=probe.id,
            sector_id=sector.id if sector else probe.sector_id,
            farm_id=farm_id,
            timestamp=event.timestamp,
            kind=event.kind,
            confidence=event.confidence,
            score=event.score,
            probability_irrigation=event.probability_irrigation,
            probability_rain=event.probability_rain,
            probability_unlogged=event.probability_unlogged,
            source_match_score=event.source_match_score,
            depth_sequence_score=event.depth_sequence_score,
            signal_strength_score=event.signal_strength_score,
            sensor_quality_score=event.sensor_quality_score,
            depths_cm=depths_cm,
            delta_vwc=event.delta_vwc,
            rainfall_mm=event.rainfall_mm,
            irrigation_mm=event.irrigation_mm,
            status="active",
            message=event.message,
        )
        db.add(row)
        persisted.append(row)

    await db.flush()
    return persisted


async def list_persisted_water_events(
    probe_id: str,
    db: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
) -> list[DetectedWaterEvent]:
    """Return persisted events for a probe, newest first."""
    stmt = (
        select(DetectedWaterEvent)
        .where(DetectedWaterEvent.probe_id == probe_id)
        .order_by(DetectedWaterEvent.timestamp.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(DetectedWaterEvent.timestamp >= since)
    if until is not None:
        stmt = stmt.where(DetectedWaterEvent.timestamp <= until)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
