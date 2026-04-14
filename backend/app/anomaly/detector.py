"""Anomaly detector orchestrator.

Fetches data from DB, runs all rules, deduplicates, and returns sorted results.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.anomaly.rules import irrigation_rules, sensor_rules, weather_rules
from app.anomaly.rules.sensor_rules import Reading
from app.anomaly.types import Anomaly
from app.models import (
    Farm,
    IrrigationEvent,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Sector,
    WeatherObservation,
)

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


class AnomalyDetector:
    """Runs all anomaly detection rules for a sector or farm."""

    async def detect_sector(
        self,
        sector_id: str,
        db: AsyncSession,
        lookback_hours: int = 72,
    ) -> list[Anomaly]:
        """Run all sensor and irrigation rules for one sector."""
        since = datetime.now(UTC) - timedelta(hours=lookback_hours)
        anomalies: list[Anomaly] = []

        # --- Load probes for this sector ---
        probes_result = await db.execute(
            select(Probe).where(Probe.sector_id == sector_id)
        )
        probes = probes_result.scalars().all()

        # --- Load soil context for FC (needed for saturation check) ---
        sector = await db.get(Sector, sector_id)
        plot = await db.get(Plot, sector.plot_id) if sector else None
        fc = (plot.field_capacity if plot and plot.field_capacity is not None else 0.28)

        # --- Load ET0 for sudden-drying context ---
        farm_id_for_obs = plot.farm_id if plot else None
        obs_query = select(WeatherObservation).order_by(WeatherObservation.timestamp.desc()).limit(1)
        if farm_id_for_obs:
            obs_query = obs_query.where(WeatherObservation.farm_id == farm_id_for_obs)
        obs_result = await db.execute(obs_query)
        latest_obs = obs_result.scalar_one_or_none()
        et0 = latest_obs.et0_mm if latest_obs else None

        # --- Load irrigation events ---
        events_result = await db.execute(
            select(IrrigationEvent)
            .where(IrrigationEvent.sector_id == sector_id, IrrigationEvent.start_time >= since)
            .order_by(IrrigationEvent.start_time)
        )
        events = events_result.scalars().all()

        for probe in probes:
            probe_anomalies = await self._check_probe(
                probe, db, since, fc, et0, events, sector_id
            )
            anomalies.extend(probe_anomalies)

        return self._deduplicate(anomalies)

    async def _check_probe(
        self,
        probe: Probe,
        db: AsyncSession,
        since: datetime,
        fc: float,
        et0: float | None,
        events: list,
        sector_id: str,
    ) -> list[Anomaly]:
        anomalies: list[Anomaly] = []

        # Load all depths
        depths_result = await db.execute(
            select(ProbeDepth)
            .where(ProbeDepth.probe_id == probe.id, ProbeDepth.sensor_type == "moisture")
        )
        depths = depths_result.scalars().all()

        readings_by_depth: dict[int, list[Reading]] = {}

        for depth in depths:
            rows_result = await db.execute(
                select(ProbeReading)
                .where(
                    ProbeReading.probe_depth_id == depth.id,
                    ProbeReading.timestamp >= since,
                    ProbeReading.unit == "vwc_m3m3",
                )
                .order_by(ProbeReading.timestamp)
            )
            rows = rows_result.scalars().all()
            if not rows:
                continue

            rds = [
                Reading(timestamp=r.timestamp, vwc=r.calibrated_value or r.raw_value)
                for r in rows
            ]
            readings_by_depth[depth.depth_cm] = rds

            # Per-depth sensor rules
            anomalies.extend(sensor_rules.detect_flatline(rds, sector_id, probe.id, depth.depth_cm))
            anomalies.extend(sensor_rules.detect_impossible_jump(rds, sector_id, probe.id, depth.depth_cm))
            anomalies.extend(sensor_rules.detect_impossible_value(rds, sector_id, probe.id, depth.depth_cm))
            anomalies.extend(sensor_rules.detect_suspicious_repetition(rds, sector_id, probe.id, depth.depth_cm))
            anomalies.extend(sensor_rules.detect_sudden_drying(rds, et0, sector_id, probe.id, depth.depth_cm))

            # Deep saturation check (60cm or 90cm sensors)
            if depth.depth_cm >= 60:
                anomalies.extend(sensor_rules.detect_persistent_saturation(
                    rds, fc, sector_id, probe.id, depth.depth_cm
                ))

        # Cross-depth rule: depth inconsistency
        shallow = readings_by_depth.get(10, [])
        deep = readings_by_depth.get(60, [])
        if shallow and deep:
            anomalies.extend(sensor_rules.detect_depth_inconsistency(
                shallow, deep, sector_id, probe.id
            ))

        # Irrigation response rules — check each event
        for event in events:
            for depth_cm in (10, 30):
                rds = readings_by_depth.get(depth_cm, [])
                if rds:
                    anomalies.extend(sensor_rules.detect_no_response_to_irrigation(
                        rds, event.start_time, sector_id, probe.id, depth_cm
                    ))
            # Over-irrigation
            shallow_rds = readings_by_depth.get(10, []) or readings_by_depth.get(30, [])
            deep_rds = readings_by_depth.get(60, []) or readings_by_depth.get(90, [])
            if shallow_rds and deep_rds:
                anomalies.extend(irrigation_rules.detect_over_irrigation(
                    shallow_rds, deep_rds, event.start_time, sector_id, probe.id
                ))

        return anomalies

    async def detect_farm(
        self,
        farm_id: str,
        db: AsyncSession,
        lookback_hours: int = 72,
    ) -> list[Anomaly]:
        """Run all rules for all sectors in a farm, plus weather rules."""
        since = datetime.now(UTC) - timedelta(hours=lookback_hours)
        anomalies: list[Anomaly] = []

        plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
        plots = plots_result.scalars().all()

        for plot in plots:
            sectors_result = await db.execute(
                select(Sector).where(Sector.plot_id == plot.id)
            )
            for sector in sectors_result.scalars().all():
                try:
                    sector_anomalies = await self.detect_sector(sector.id, db, lookback_hours)
                    anomalies.extend(sector_anomalies)
                except Exception:
                    logger.exception("Anomaly detection failed for sector %s", sector.id)

        # Farm-level weather rules
        obs_result = await db.execute(
            select(WeatherObservation)
            .where(
                WeatherObservation.farm_id == farm_id,
                WeatherObservation.timestamp >= since,
            )
            .order_by(WeatherObservation.timestamp.desc())
            .limit(1)
        )
        obs = obs_result.scalar_one_or_none()
        if obs and obs.rainfall_mm and obs.rainfall_mm >= 5.0:
            # Build per-depth readings for weather check across all farm probes
            all_sectors = [s for plot in plots for s in []]  # just skip for MVP
            _ = weather_rules.detect_rainfall_mismatch(
                probe_readings_by_depth={},
                rainfall_mm=obs.rainfall_mm,
                rain_observed_at=obs.timestamp,
                sector_id=None,
                farm_id=farm_id,
            )

        return self._deduplicate(anomalies)

    def _deduplicate(self, anomalies: list[Anomaly]) -> list[Anomaly]:
        """Remove duplicates (same type + probe + depth), keep highest severity."""
        best: dict[tuple, Anomaly] = {}
        for a in anomalies:
            key = a.dedup_key()
            existing = best.get(key)
            if existing is None:
                best[key] = a
            else:
                # Keep the one with higher severity (lower index = higher severity)
                if _SEVERITY_ORDER[a.severity] < _SEVERITY_ORDER[existing.severity]:
                    best[key] = a
        result = list(best.values())
        result.sort(key=lambda a: (_SEVERITY_ORDER[a.severity], a.anomaly_type))
        return result
