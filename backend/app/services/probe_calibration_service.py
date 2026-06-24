"""Probe-calibration service.

Computes per-sector FC/refill bounds from each probe's own VWC envelope (via
AutoCalibrationService) and upserts them into the probe_calibration table. Run
weekly per farm by the scheduler. Pure computation lives in engine/auto_calibration.py.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.auto_calibration import AutoCalibrationService

logger = logging.getLogger(__name__)


class ProbeCalibrationService:
    def __init__(self) -> None:
        self._calibrator = AutoCalibrationService()

    async def compute_and_save(self, sector_id: str, db: AsyncSession):
        from app.models.probe_calibration import ProbeCalibration

        result = await self._calibrator.compute_sector_calibration(sector_id, db)
        if result is None:
            return None

        now = datetime.now(UTC)
        existing = (await db.execute(
            select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
        )).scalar_one_or_none()

        if existing:
            existing.observed_fc = result.observed_fc
            existing.observed_refill = result.observed_refill
            existing.method = result.method
            existing.num_cycles = result.num_cycles
            existing.consistency = result.consistency
            existing.window_days = result.window_days
            existing.computed_at = now
            await db.flush()
            return existing

        row = ProbeCalibration(
            sector_id=sector_id,
            observed_fc=result.observed_fc,
            observed_refill=result.observed_refill,
            method=result.method,
            num_cycles=result.num_cycles,
            consistency=result.consistency,
            window_days=result.window_days,
            computed_at=now,
        )
        db.add(row)
        await db.flush()
        return row

    async def compute_all_for_farm(self, farm_id: str, db: AsyncSession) -> int:
        """Recompute calibration for every sector in a farm. Caller commits.

        Per-sector failures are swallowed so one bad sector cannot abort the farm.
        """
        from app.models import Plot, Sector

        sectors = (await db.execute(
            select(Sector).join(Plot, Sector.plot_id == Plot.id)
            .where(Plot.farm_id == farm_id)
        )).scalars().all()

        calibrated = 0
        for sector in sectors:
            try:
                saved = await self.compute_and_save(str(sector.id), db)
                if saved is not None:
                    calibrated += 1
            except Exception:
                logger.exception("Probe calibration failed for sector %s", sector.id)
        return calibrated
