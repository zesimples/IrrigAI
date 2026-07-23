"""Persistence and reconciliation for probe-derived water events.

The detector is stateless and probe-only. Active automatic detections form a
replaceable projection over a rolling readings window; confirmed and rejected
rows are immutable user feedback and are never overwritten by recalculation.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable
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
from app.schemas.probe import DepthReadings, ProbeDetectedEvent, TimeSeriesPoint

DEFAULT_LOOKBACK_DAYS = 7
MIN_REPROCESS_HOURS = 48
DETECTOR_PREROLL_HOURS = 12
FEEDBACK_MATCH_HOURS = 2


async def _load_readings_window(
    db: AsyncSession,
    probe: Probe,
    since: datetime,
    until: datetime,
) -> list[DepthReadings]:
    """Load and de-duplicate VWC readings grouped by physical depth."""
    depth_rows = (
        (
            await db.execute(
                select(ProbeDepth).where(
                    ProbeDepth.probe_id == probe.id,
                    ProbeDepth.sensor_type.in_(("soil_moisture", "moisture")),
                )
            )
        )
        .scalars()
        .all()
    )

    ids_by_depth: dict[int, list[str]] = defaultdict(list)
    for depth in depth_rows:
        ids_by_depth[depth.depth_cm].append(depth.id)

    result: list[DepthReadings] = []
    for depth_cm, depth_ids in sorted(ids_by_depth.items()):
        rows = (
            (
                await db.execute(
                    select(ProbeReading)
                    .where(
                        ProbeReading.probe_depth_id.in_(depth_ids),
                        ProbeReading.timestamp >= since,
                        ProbeReading.timestamp <= until,
                        ProbeReading.unit == "vwc_m3m3",
                    )
                    .order_by(ProbeReading.timestamp, ProbeReading.id)
                )
            )
            .scalars()
            .all()
        )

        # Provider remapping can leave more than one channel at the same physical
        # depth. Use their median rather than allowing an arbitrary duplicate
        # channel to dominate the detector.
        values_by_timestamp: dict[datetime, list[tuple[float, str]]] = defaultdict(list)
        for row in rows:
            values_by_timestamp[row.timestamp].append(
                (
                    row.calibrated_value if row.calibrated_value is not None else row.raw_value,
                    row.quality_flag,
                )
            )
        points_by_timestamp = {
            timestamp: TimeSeriesPoint(
                timestamp=timestamp,
                vwc=statistics.median(value for value, _quality in values),
                quality=_combined_quality(quality for _value, quality in values),
            )
            for timestamp, values in values_by_timestamp.items()
        }
        result.append(
            DepthReadings(
                depth_cm=depth_cm,
                readings=[
                    points_by_timestamp[timestamp] for timestamp in sorted(points_by_timestamp)
                ],
            )
        )
    return result


def _combined_quality(qualities: Iterable[str]) -> str:
    values = set(qualities)
    if values == {"invalid"}:
        return "invalid"
    if values == {"ok"}:
        return "ok"
    return "suspect"


async def detect_and_persist_water_events(
    probe_id: str,
    db: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[DetectedWaterEvent]:
    """Recalculate automatic events while preserving user-reviewed feedback."""
    requested_until = until or datetime.now(UTC)
    requested_since = since or (requested_until - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    detection_since = min(
        requested_since,
        requested_until - timedelta(hours=MIN_REPROCESS_HOURS),
    )
    readings_since = detection_since - timedelta(hours=DETECTOR_PREROLL_HOURS)

    probe = await db.get(Probe, probe_id)
    if probe is None:
        return []

    sector = await db.get(Sector, probe.sector_id)
    plot = await db.get(Plot, sector.plot_id) if sector else None
    farm_id = plot.farm_id if plot else None

    depths = await _load_readings_window(
        db,
        probe,
        readings_since,
        requested_until,
    )
    if not any(depth.readings for depth in depths):
        return []

    detected: list[ProbeDetectedEvent] = await detect_water_events(
        depths=depths,
        since=detection_since,
        until=requested_until,
    )
    existing_rows = list(
        (
            await db.execute(
                select(DetectedWaterEvent).where(
                    DetectedWaterEvent.probe_id == probe.id,
                    DetectedWaterEvent.timestamp >= detection_since,
                    DetectedWaterEvent.timestamp <= requested_until,
                )
            )
        )
        .scalars()
        .all()
    )
    feedback_rows = [row for row in existing_rows if row.status != "active"]
    unmatched_active = {
        (row.timestamp, row.kind): row for row in existing_rows if row.status == "active"
    }

    persisted: list[DetectedWaterEvent] = []
    for event in detected:
        if _nearest_feedback(event, feedback_rows) is not None:
            continue

        key = (event.timestamp, event.kind)
        row = unmatched_active.pop(key, None)
        if row is None:
            row = DetectedWaterEvent(
                id=str(uuid.uuid4()),
                probe_id=probe.id,
                sector_id=sector.id if sector else probe.sector_id,
                farm_id=farm_id,
                timestamp=event.timestamp,
                kind=event.kind,
                status="active",
            )
            db.add(row)

        _apply_detection(row, event)
        persisted.append(row)

    # Rows no longer reproduced by the detector are stale automatic projections.
    # Human-confirmed and rejected rows above remain intact.
    for stale_row in unmatched_active.values():
        await db.delete(stale_row)

    await db.flush()
    return persisted


def _nearest_feedback(
    event: ProbeDetectedEvent,
    feedback_rows: list[DetectedWaterEvent],
) -> DetectedWaterEvent | None:
    candidates = [
        row
        for row in feedback_rows
        if abs((row.timestamp - event.timestamp).total_seconds()) <= FEEDBACK_MATCH_HOURS * 3600
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: abs((row.timestamp - event.timestamp).total_seconds()),
    )


def _apply_detection(
    row: DetectedWaterEvent,
    event: ProbeDetectedEvent,
) -> None:
    row.confidence = event.confidence
    row.score = event.score
    row.probability_irrigation = event.probability_irrigation
    row.probability_rain = event.probability_rain
    row.probability_unlogged = event.probability_unlogged
    row.source_match_score = event.source_match_score
    row.depth_sequence_score = event.depth_sequence_score
    row.signal_strength_score = event.signal_strength_score
    row.sensor_quality_score = event.sensor_quality_score
    row.depths_cm = list(event.depths_cm)
    row.delta_vwc = event.delta_vwc
    row.rainfall_mm = None
    row.irrigation_mm = None
    row.matched_irrigation_event_id = None
    row.matched_weather_observation_id = None
    row.message = event.message


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
