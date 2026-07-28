"""Probe-calibration service.

Computes per-sector FC/refill bounds from each probe's own VWC envelope (via
AutoCalibrationService) and upserts them into the probe_calibration table. Run
weekly per farm by the scheduler. Pure computation lives in engine/auto_calibration.py.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.auto_calibration import AutoCalibrationService
from app.engine.calibration_policy import (
    AUTO_APPLY_FLATLINE_STD_M3M3,
    AutoApplyDecision,
    CalibrationQuality,
)

logger = logging.getLogger(__name__)


@dataclass
class CalibrationSweepCounts:
    """Outcome tally for one farm's weekly calibration sweep."""

    applied: int = 0
    skipped: int = 0
    no_candidate: int = 0
    candidates: int = 0
    failed: int = 0


@dataclass(frozen=True)
class AutoApplyOutcome:
    """A decision plus the numbers that explain it, for logging.

    Blocked runs persist no row, so the log line is the ONLY trace of what the
    sweep saw. Carrying the values out of `compute_and_auto_apply` lets the caller
    log them *after* the per-sector savepoint has released, so a rolled-back sector
    can never leave a line claiming it was applied. The values live here rather than
    on the frozen `AutoApplyDecision` so the pure policy — and its fixture-free
    tests — stay a function of thresholds only.
    """

    decision: AutoApplyDecision
    before_fc: float | None = None
    before_refill: float | None = None
    before_source: str | None = None
    candidate_fc: float | None = None
    candidate_refill: float | None = None
    method: str | None = None

    @property
    def apply(self) -> bool:
        return self.decision.apply

    @property
    def reason(self) -> str:
        return self.decision.reason


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
        from app.models import ProbeCalibration

        result = await self._calibrator.compute_sector_calibration(sector_id, db)
        if result is None:
            return None

        existing = (await db.execute(
            select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
        )).scalar_one_or_none()
        now = datetime.now(UTC)
        run = self._new_run(
            sector_id, result, existing,
            source=source, created_by_id=created_by_id, computed_at=now,
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

    def _new_run(
        self,
        sector_id: str,
        result,
        existing,
        *,
        source: str,
        created_by_id: str | None,
        computed_at,
    ):
        from app.models import ProbeCalibrationRun

        return ProbeCalibrationRun(
            sector_id=sector_id,
            observed_fc=result.observed_fc,
            observed_refill=result.observed_refill,
            method=result.method,
            num_cycles=result.num_cycles,
            consistency=result.consistency,
            window_days=result.window_days,
            computed_at=computed_at,
            source=source,
            status="candidate",
            previous_fc=existing.observed_fc if existing else None,
            previous_refill=existing.observed_refill if existing else None,
            created_by_id=created_by_id,
        )

    async def compute_and_auto_apply(
        self, sector_id: str, db: AsyncSession
    ) -> AutoApplyOutcome:
        """Compute a candidate and promote it only if the policy allows.

        A blocked candidate persists NOTHING — no history row, no projection
        change. Unlike the manual endpoints, this path never clears
        SectorCropProfile.is_customized: a deliberate human soil edit outranks
        unattended measurement.

        Returns an AutoApplyOutcome so the caller can log the before/candidate
        values once the sector's savepoint has released.
        """
        from sqlalchemy import select

        from app.engine.calibration_policy import (
            REASON_NO_CANDIDATE,
            evaluate_auto_apply,
        )
        from app.engine.pipeline import resolve_sector_soil_bounds
        from app.engine.soil_bounds import SOURCE_PROBE_CALIBRATED, SOURCE_SCP_OVERRIDE
        from app.models import ProbeCalibration
        from app.services.audit_service import audit

        result = await self._calibrator.compute_sector_calibration(sector_id, db)
        if result is None:
            return AutoApplyOutcome(AutoApplyDecision(False, REASON_NO_CANDIDATE))

        before = await resolve_sector_soil_bounds(sector_id, db)
        existing = (await db.execute(
            select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
        )).scalar_one_or_none()
        quality = await self.build_quality(sector_id, db)

        # Gate on the source the resolver actually chose, not on raw DB flags:
        # SectorCropProfile.is_customized is set by any profile edit even when the
        # soil fields are NULL (so the preset still governs), and a >90-day-old
        # probe_calibration row is ignored by the resolver (so `before` is a preset
        # the cap must not be measured against — that deadlocks the sector forever).
        decision = evaluate_auto_apply(
            result,
            before,
            quality,
            bounds_from_manual_override=before.source == SOURCE_SCP_OVERRIDE,
            bounds_from_prior_calibration=before.source == SOURCE_PROBE_CALIBRATED,
        )
        outcome = AutoApplyOutcome(
            decision,
            before_fc=before.fc,
            before_refill=before.pwp,
            before_source=before.source,
            candidate_fc=result.observed_fc,
            candidate_refill=result.observed_refill,
            method=result.method,
        )
        if not decision.apply:
            return outcome

        now = datetime.now(UTC)
        run = self._new_run(
            sector_id, result, existing,
            source="scheduled", created_by_id=None, computed_at=now,
        )
        db.add(run)
        await db.flush()
        await self.apply_run(run, db)

        await audit.log(
            "probe_calibration_auto_applied",
            "sector",
            sector_id,
            db,
            user_id=None,
            before_data={"source": before.source, "fc": before.fc, "pwp": before.pwp},
            after_data={
                "observed_fc": result.observed_fc,
                "observed_refill": result.observed_refill,
                "method": result.method,
                "run_id": str(run.id),
            },
        )
        return outcome

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

    async def compute_all_for_farm(
        self, farm_id: str, db: AsyncSession, *, auto_apply: bool = False
    ) -> CalibrationSweepCounts:
        """Recompute calibration for every active sector in a farm. Caller commits.

        Each sector runs inside a savepoint so a failed flush rolls back only that
        sector — without it, a single failure leaves the session needing a rollback
        and every later sector raises PendingRollbackError.

        With `auto_apply` the policy may promote results unattended; without it the
        job records candidates only, exactly as before.
        """
        from sqlalchemy import select

        from app.engine.calibration_policy import REASON_NO_CANDIDATE
        from app.metrics import calibration_auto_apply_total
        from app.models import Plot, Sector

        sectors = (await db.execute(
            select(Sector).join(Plot, Sector.plot_id == Plot.id)
            .where(
                Plot.farm_id == farm_id,
                Plot.is_archived.is_(False),
                Sector.is_archived.is_(False),
            )
        )).scalars().all()

        counts = CalibrationSweepCounts()
        for sector in sectors:
            sector_id = str(sector.id)
            try:
                async with db.begin_nested():
                    if not auto_apply:
                        recorded = await self.compute_and_record(
                            sector_id, db, apply=False, source="scheduled"
                        )
                        if recorded is not None:
                            counts.candidates += 1
                        continue

                    decision = await self.compute_and_auto_apply(sector_id, db)
                    if decision.apply:
                        counts.applied += 1
                        calibration_auto_apply_total.labels(
                            "applied", decision.reason, "any"
                        ).inc()
                    elif decision.reason == REASON_NO_CANDIDATE:
                        counts.no_candidate += 1
                        calibration_auto_apply_total.labels(
                            "no_candidate", decision.reason, "none"
                        ).inc()
                    else:
                        counts.skipped += 1
                        calibration_auto_apply_total.labels(
                            "skipped", decision.reason, "any"
                        ).inc()
            except Exception:
                counts.failed += 1
                calibration_auto_apply_total.labels("error", "exception", "none").inc()
                logger.exception("Probe calibration failed for sector %s", sector.id)
        return counts
