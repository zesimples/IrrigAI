"""Irrigation-fingerprint service.

Learns each sector's habitual irrigation dose from persisted probe-detected
irrigation events (DetectedWaterEvent) + raw VWC readings, and upserts one
irrigation_fingerprint row per sector. Run weekly per farm by the scheduler.
Pure computation lives in engine/irrigation_fingerprint.py.

Event hygiene (spec): rejected events excluded; confirmed events always count;
unreviewed ("active") events count only when the detector classified them as
irrigation with medium/high confidence. Rain-kind events never count.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.irrigation_fingerprint import (
    FINGERPRINT_WINDOW_DAYS,
    compute_event_dose,
    compute_fingerprint,
    layer_thicknesses_mm,
)

logger = logging.getLogger(__name__)

_READINGS_MARGIN_H = 12  # cover baseline/peak windows around edge events


class IrrigationFingerprintService:
    async def compute_and_save(self, sector_id: str, db: AsyncSession):
        from app.models import (
            DetectedWaterEvent,
            Probe,
            ProbeDepth,
            ProbeReading,
            SectorCropProfile,
        )
        from app.models.irrigation_fingerprint import IrrigationFingerprint

        now = datetime.now(UTC)
        since = now - timedelta(days=FINGERPRINT_WINDOW_DAYS)

        probes = (
            (
                await db.execute(
                    select(Probe).where(Probe.sector_id == sector_id).order_by(Probe.created_at)
                )
            )
            .scalars()
            .all()
        )
        if not probes:
            return None
        probe = probes[0]

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
        if not depth_rows:
            return None
        depth_by_id = {d.id: d.depth_cm for d in depth_rows}

        events = (
            (
                await db.execute(
                    select(DetectedWaterEvent)
                    .where(
                        DetectedWaterEvent.sector_id == sector_id,
                        DetectedWaterEvent.timestamp >= since,
                        DetectedWaterEvent.kind == "irrigation",
                        DetectedWaterEvent.status != "rejected",
                    )
                    .order_by(DetectedWaterEvent.timestamp)
                )
            )
            .scalars()
            .all()
        )
        usable_events = [
            e for e in events if e.status == "confirmed" or e.confidence in ("medium", "high")
        ]
        if len(usable_events) < 3:
            return None

        readings = (
            (
                await db.execute(
                    select(ProbeReading)
                    .where(
                        ProbeReading.probe_depth_id.in_(list(depth_by_id.keys())),
                        ProbeReading.timestamp >= since - timedelta(hours=_READINGS_MARGIN_H),
                        ProbeReading.unit == "vwc_m3m3",
                        ProbeReading.quality_flag == "ok",
                    )
                    .order_by(ProbeReading.timestamp)
                )
            )
            .scalars()
            .all()
        )
        series_by_depth: dict[int, list[tuple[datetime, float]]] = {}
        for r in readings:
            depth_cm = depth_by_id.get(r.probe_depth_id)
            if depth_cm is None:
                continue
            value = r.calibrated_value if r.calibrated_value is not None else r.raw_value
            if value is None:
                continue
            series_by_depth.setdefault(depth_cm, []).append((r.timestamp, value))

        scp = (
            await db.execute(
                select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
            )
        ).scalar_one_or_none()
        root_depth_cm = (
            scp.root_depth_mature_m * 100.0 if scp is not None and scp.root_depth_mature_m else None
        )
        layers = layer_thicknesses_mm(sorted(series_by_depth.keys()), root_depth_cm)

        doses = []
        for event in usable_events:
            dose = compute_event_dose(series_by_depth, event.timestamp, layers)
            if dose is not None:
                doses.append(dose)

        result = compute_fingerprint(doses)
        if result is None:
            return None

        existing = (
            await db.execute(
                select(IrrigationFingerprint).where(IrrigationFingerprint.sector_id == sector_id)
            )
        ).scalar_one_or_none()
        if existing:
            existing.typical_event_net_mm = result.typical_event_net_mm
            existing.typical_event_duration_min = result.typical_event_duration_min
            existing.n_events = result.n_events
            existing.consistency = result.consistency
            existing.confidence = result.confidence
            existing.window_days = result.window_days
            existing.computed_at = now
            await db.flush()
            return existing

        row = IrrigationFingerprint(
            sector_id=sector_id,
            typical_event_net_mm=result.typical_event_net_mm,
            typical_event_duration_min=result.typical_event_duration_min,
            n_events=result.n_events,
            consistency=result.consistency,
            confidence=result.confidence,
            window_days=result.window_days,
            computed_at=now,
        )
        db.add(row)
        await db.flush()
        return row

    async def compute_all_for_farm(self, farm_id: str, db: AsyncSession) -> int:
        """Recompute fingerprints for every sector in a farm. Caller commits.

        Per-sector failures are swallowed so one bad sector cannot abort the farm.
        """
        from app.models import Plot, Sector

        sectors = (
            (
                await db.execute(
                    select(Sector)
                    .join(Plot, Sector.plot_id == Plot.id)
                    .where(Plot.farm_id == farm_id)
                )
            )
            .scalars()
            .all()
        )

        computed = 0
        for sector in sectors:
            try:
                saved = await self.compute_and_save(str(sector.id), db)
                if saved is not None:
                    computed += 1
            except Exception:
                logger.exception("Irrigation fingerprint failed for sector %s", sector.id)
        return computed
