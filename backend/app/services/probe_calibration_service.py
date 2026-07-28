"""Probe-calibration service.

Computes per-sector FC/refill bounds from each probe's own VWC envelope (via
AutoCalibrationService) and upserts them into the probe_calibration table. Run
weekly per farm by the scheduler. Pure computation lives in engine/auto_calibration.py.
"""
from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.auto_calibration import AutoCalibrationService
from app.engine.calibration_policy import (
    AUTO_APPLY_FLATLINE_STD_M3M3,
    CalibrationQuality,
)

logger = logging.getLogger(__name__)


class ProbeCalibrationService:
    def __init__(self) -> None:
        self._calibrator = AutoCalibrationService()

    async def compute_and_record(
        self,
        sector_id: str,
        db: AsyncSession,
        *,
        apply: bool,
        source: str,
        created_by_id: str | None = None,
    ):
        """Compute an immutable run and optionally promote it to active bounds."""
        from app.models import ProbeCalibration, ProbeCalibrationRun

        result = await self._calibrator.compute_sector_calibration(sector_id, db)
        if result is None:
            return None

        existing = (await db.execute(
            select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
        )).scalar_one_or_none()
        now = datetime.now(UTC)
        run = ProbeCalibrationRun(
            sector_id=sector_id,
            observed_fc=result.observed_fc,
            observed_refill=result.observed_refill,
            method=result.method,
            num_cycles=result.num_cycles,
            consistency=result.consistency,
            window_days=result.window_days,
            computed_at=now,
            source=source,
            status="candidate",
            previous_fc=existing.observed_fc if existing else None,
            previous_refill=existing.observed_refill if existing else None,
            created_by_id=created_by_id,
        )
        db.add(run)
        await db.flush()

        active = existing
        if apply:
            active = await self.apply_run(run, db)
        return active, run

    async def compute_and_save(
        self,
        sector_id: str,
        db: AsyncSession,
        *,
        source: str = "manual",
        created_by_id: str | None = None,
    ):
        recorded = await self.compute_and_record(
            sector_id,
            db,
            apply=True,
            source=source,
            created_by_id=created_by_id,
        )
        if recorded is None:
            return None
        active, _run = recorded
        return active

    async def apply_run(self, run, db: AsyncSession):
        """Promote a history row, superseding the previously applied run."""
        from app.models import ProbeCalibration, ProbeCalibrationRun

        now = datetime.now(UTC)
        previously_applied = (await db.execute(
            select(ProbeCalibrationRun).where(
                ProbeCalibrationRun.sector_id == run.sector_id,
                ProbeCalibrationRun.status == "applied",
                ProbeCalibrationRun.id != run.id,
            )
        )).scalars().all()
        for previous in previously_applied:
            previous.status = "superseded"

        existing = (await db.execute(
            select(ProbeCalibration).where(ProbeCalibration.sector_id == run.sector_id)
        )).scalar_one_or_none()

        if existing:
            row = existing
            row.observed_fc = run.observed_fc
            row.observed_refill = run.observed_refill
            row.method = run.method
            row.num_cycles = run.num_cycles
            row.consistency = run.consistency
            row.window_days = run.window_days
            row.computed_at = run.computed_at
        else:
            row = ProbeCalibration(
                sector_id=run.sector_id,
                observed_fc=run.observed_fc,
                observed_refill=run.observed_refill,
                method=run.method,
                num_cycles=run.num_cycles,
                consistency=run.consistency,
                window_days=run.window_days,
                computed_at=run.computed_at,
            )
            db.add(row)
        run.status = "applied"
        run.applied_at = now
        await db.flush()
        return row

    async def build_quality(
        self, sector_id: str, db: AsyncSession
    ) -> CalibrationQuality:
        """Deterministic trust signals for the calibration window.

        Two queries: one join for the per-depth VWC series, one for the sector's
        newest probe contact. Deliberately independent of
        compute_sector_calibration, which does not expose the series it loaded —
        refactoring that safety-critical function to share it is not worth the
        risk for two cheap weekly queries.
        """
        from sqlalchemy import func, select

        from app.engine.auto_calibration import CALIB_WINDOW_DAYS
        from app.models import Probe, ProbeDepth, ProbeReading

        since = datetime.now(UTC) - timedelta(days=CALIB_WINDOW_DAYS)

        rows = (await db.execute(
            select(
                ProbeDepth.depth_cm,
                ProbeReading.raw_value,
                ProbeReading.calibrated_value,
            )
            .join(ProbeReading, ProbeReading.probe_depth_id == ProbeDepth.id)
            .join(Probe, Probe.id == ProbeDepth.probe_id)
            .where(
                Probe.sector_id == sector_id,
                # Real data uses "soil_moisture"; older/mock data uses "moisture".
                ProbeDepth.sensor_type.in_(("soil_moisture", "moisture")),
                ProbeReading.timestamp >= since,
                ProbeReading.unit == "vwc_m3m3",
                ProbeReading.quality_flag == "ok",
            )
        )).all()

        by_depth: dict[int, list[float]] = {}
        for depth_cm, raw, calibrated in rows:
            value = calibrated if calibrated is not None else raw
            if value is not None:
                by_depth.setdefault(depth_cm, []).append(float(value))

        # A depth needs enough points to judge stability (same floor as probe_signal).
        judgeable = [vals for vals in by_depth.values() if len(vals) >= 4]
        all_flat = bool(judgeable) and all(
            statistics.stdev(vals) < AUTO_APPLY_FLATLINE_STD_M3M3 for vals in judgeable
        )

        last_reading_at = (await db.execute(
            select(func.max(Probe.last_reading_at)).where(Probe.sector_id == sector_id)
        )).scalar()

        hours: float | None = None
        if last_reading_at is not None:
            if last_reading_at.tzinfo is None:
                last_reading_at = last_reading_at.replace(tzinfo=UTC)
            hours = (datetime.now(UTC) - last_reading_at).total_seconds() / 3600

        return CalibrationQuality(
            probe_hours_since_reading=hours,
            all_depths_flatlined=all_flat,
        )

    async def compute_all_for_farm(self, farm_id: str, db: AsyncSession) -> int:
        """Recompute calibration for every sector in a farm. Caller commits.

        Per-sector failures are swallowed so one bad sector cannot abort the farm.
        """
        from app.models import Plot, Sector

        sectors = (await db.execute(
            select(Sector).join(Plot, Sector.plot_id == Plot.id)
            .where(
                Plot.farm_id == farm_id,
                Plot.is_archived.is_(False),
                Sector.is_archived.is_(False),
            )
        )).scalars().all()

        calibrated = 0
        for sector in sectors:
            try:
                result = await self.compute_and_record(
                    str(sector.id), db, apply=False, source="scheduled"
                )
                if result is not None:
                    calibrated += 1
            except Exception:
                logger.exception("Probe calibration failed for sector %s", sector.id)
        return calibrated
