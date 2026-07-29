"""Background scheduler — APScheduler async jobs.

Jobs:
  - Alert check:               every 2 hours
  - Recommendation generation: daily at 05:00 UTC
  - Data ingestion:            every 15 minutes

Each job acquires a Redis lock before running so jobs cannot double-run if
the worker is restarted mid-job or in a hypothetical multi-replica setup.
TTLs are generous (>= full job interval) so a stuck lock self-expires.

This module is imported only by app/worker.py — never by the HTTP server.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.heartbeat import record_heartbeat
from app.job_lock import JobLock
from app.metrics import scheduler_farm_failures_total, scheduler_job_runs_total

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def classify_per_farm_run(farms_ok: int, farms_failed: int) -> str:
    """Scheduler-metric status for a job that processes every farm in a loop.

    ``failure`` only when at least one farm failed *and none* succeeded — the
    total-outage case that previously logged ``success`` because per-farm
    exceptions were swallowed. A mix is ``partial_failure``; an empty install or
    a clean sweep is ``success``.
    """
    if farms_failed == 0:
        return "success"
    if farms_ok == 0:
        return "failure"
    return "partial_failure"


async def _run_per_farm_job(
    *,
    job_name: str,
    lock_name: str,
    ttl: int,
    handle_farm: Callable[[object, object], Awaitable[None]],
) -> None:
    """Shared skeleton for jobs that run `handle_farm` against every farm.

    Acquires the Redis lock, counts per-farm successes/failures, surfaces them on
    the metrics (`scheduler_farm_failures_total` + a classified run status), logs
    a WARNING summary when any farm fails, and stamps the liveness heartbeat.
    """
    async with JobLock(lock_name, ttl=ttl) as acquired:
        if not acquired:
            scheduler_job_runs_total.labels(job_name, "skipped").inc()
            return

        from app.database import get_db
        from app.active_records import active_farms_stmt

        logger.info("Scheduler: %s at %s", job_name, datetime.now(UTC))
        farms_ok = 0
        farms_failed = 0
        try:
            async for db in get_db():
                farms = (await db.execute(active_farms_stmt())).scalars().all()
                for farm in farms:
                    try:
                        await handle_farm(farm, db)
                        farms_ok += 1
                    except Exception:
                        farms_failed += 1
                        scheduler_farm_failures_total.labels(job_name).inc()
                        logger.exception("%s failed for farm %s", job_name, farm.id)
            status = classify_per_farm_run(farms_ok, farms_failed)
            if farms_failed:
                logger.warning(
                    "%s: %d/%d farms failed (status=%s)",
                    job_name,
                    farms_failed,
                    farms_ok + farms_failed,
                    status,
                )
            scheduler_job_runs_total.labels(job_name, status).inc()
        except Exception:
            scheduler_job_runs_total.labels(job_name, "failure").inc()
            raise
        finally:
            record_heartbeat()


async def _run_alert_check() -> None:
    from app.alerts.engine import AlertEngine

    alert_engine = AlertEngine()

    async def handle(farm, db) -> None:
        alerts = await alert_engine.run_farm_alerts(farm.id, db)
        logger.info("Alert check: farm=%s reconciled %d alerts", farm.id, len(alerts))

    await _run_per_farm_job(
        job_name="alert_check", lock_name="alert_check", ttl=7_200, handle_farm=handle
    )


async def _run_recommendation_generation() -> None:
    from app.services.recommendation_service import generate_for_farm

    async def handle(farm, db) -> None:
        results = await generate_for_farm(farm.id, db)
        logger.info("Recommendations: farm=%s generated %d", farm.id, len(results))

    await _run_per_farm_job(
        job_name="daily_recommendations",
        lock_name="daily_recommendations",
        ttl=3_600,
        handle_farm=handle,
    )


async def _run_data_ingestion() -> None:
    from app.services.ingestion import ingest_farm
    from app.services.anomaly_service import run_for_farm
    from app.services.recommendation_outcome_service import evaluate_recent_for_farm

    async def handle(farm, db) -> None:
        await ingest_farm(farm.id, db, lookback_hours=4)
        anomalies = await run_for_farm(farm.id, db)
        logger.info(
            "Post-ingestion anomaly detection: farm=%s active=%d",
            farm.id,
            len(anomalies),
        )
        outcomes = await evaluate_recent_for_farm(farm.id, db)
        logger.info("Recommendation outcomes: farm=%s evaluated=%d", farm.id, outcomes)

    await _run_per_farm_job(
        job_name="data_ingestion", lock_name="data_ingestion", ttl=900, handle_farm=handle
    )


async def _run_flowmeter_ingestion() -> None:
    async with JobLock("flowmeter_ingestion", ttl=1_200) as acquired:
        if not acquired:
            scheduler_job_runs_total.labels("flowmeter_ingestion", "skipped").inc()
            return

        from app.alerts.flowmeter_flow_rate_alerts import FlowmeterFlowRateAlertChecker
        from app.database import get_db
        from app.metrics import flowmeter_device_ingestion_total
        from app.active_records import active_farms_stmt
        from app.services.flowmeter_ingestion import (
            FlowmeterIngestionService,
            classify_flowmeter_run,
        )
        from app.services.recommendation_outcome_service import evaluate_recent_for_farm

        logger.info("Scheduler: flowmeter ingestion at %s", datetime.now(UTC))
        service = FlowmeterIngestionService()

        try:
            total_inserted = 0
            devices_ok = 0
            devices_failed = 0
            farms_failed = 0
            async for db in get_db():
                farms = (await db.execute(active_farms_stmt())).scalars().all()
                for farm in farms:
                    try:
                        summary = await service.ingest_farm(farm.id, db)
                        total_inserted += summary.get("readings_inserted", 0)
                        devices_ok += summary.get("devices_succeeded", 0)
                        devices_failed += summary.get("devices_failed", 0)
                        await evaluate_recent_for_farm(farm.id, db)
                    except Exception:
                        farms_failed += 1
                        scheduler_farm_failures_total.labels("flowmeter_ingestion").inc()
                        logger.exception("Flowmeter ingestion failed for farm %s", farm.id)
                    try:
                        await FlowmeterFlowRateAlertChecker().check_and_persist(str(farm.id), db)
                    except Exception:
                        logger.exception("Flow-rate alert check failed for farm %s", farm.id)
            if devices_ok:
                flowmeter_device_ingestion_total.labels("success").inc(devices_ok)
            if devices_failed:
                flowmeter_device_ingestion_total.labels("failure").inc(devices_failed)
            # Record the real outcome: an all-devices-failed run (e.g. 406 on every
            # device) is a failure, not a success — even though the job didn't raise.
            status = classify_flowmeter_run(total_inserted, devices_failed)
            if farms_failed:
                logger.warning("flowmeter_ingestion: %d farms raised during ingest", farms_failed)
            scheduler_job_runs_total.labels("flowmeter_ingestion", status).inc()
        except Exception:
            scheduler_job_runs_total.labels("flowmeter_ingestion", "failure").inc()
            raise
        finally:
            record_heartbeat()


async def _run_reference_recompute() -> None:
    from app.services.flowmeter_reference import FlowmeterReferenceService

    svc = FlowmeterReferenceService()

    async def handle(farm, db) -> None:
        await svc.compute_all_for_farm(str(farm.id), db)
        await db.commit()

    await _run_per_farm_job(
        job_name="reference_recompute",
        lock_name="reference_recompute",
        ttl=3_600,
        handle_farm=handle,
    )


async def _drain_calibration_sweep_queue() -> None:
    """Run one queued calibration sweep, if any.

    Separate from the Monday job because a manual sweep targets one farm and
    must not wait for the whole-estate pass. Both take the same per-farm lock,
    so they can never collide on one farm.
    """
    import time

    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.metrics import calibration_sweep_duration_seconds, calibration_sweep_total
    from app.models import CalibrationSweepRun, Plot, Sector
    from app.services.calibration_sweep_service import (
        finish_run,
        mark_running,
        pop_queued_run_id,
        record_progress,
        requeue_run_id,
    )
    from app.services.probe_calibration_service import (
        CalibrationSweepCounts,
        ProbeCalibrationService,
    )

    run_id = await pop_queued_run_id()
    if run_id is None:
        return

    async with AsyncSessionLocal() as session:
        run = await session.get(CalibrationSweepRun, run_id)
        if run is None:
            logger.warning("Calibration sweep queue held unknown run %s — dropping", run_id)
            return
        farm_id = str(run.farm_id)
        auto_apply = bool(run.auto_apply)
        run_status = run.status

    if run_status != "queued":
        logger.info("Calibration sweep run %s is %s, not queued — skipping", run_id, run_status)
        return

    async with JobLock(f"calibration_sweep:{farm_id}", ttl=3_600) as acquired:
        if not acquired:
            # The Monday job (or a previous tick) owns this farm. The request is
            # valid — put it back and try on a later tick. queued_at staleness
            # is the backstop if the lock never frees.
            logger.info("Calibration sweep for farm %s deferred — lock held", farm_id)
            await requeue_run_id(run_id)
            return

        async with AsyncSessionLocal() as session:
            total = (await session.execute(
                select(func.count(Sector.id))
                .join(Plot, Sector.plot_id == Plot.id)
                .where(
                    Plot.farm_id == farm_id,
                    Plot.is_archived.is_(False),
                    Sector.is_archived.is_(False),
                )
            )).scalar() or 0

        await mark_running(run_id, sectors_total=total)
        logger.info(
            "Calibration sweep starting: run=%s farm=%s sectors=%d auto_apply=%s",
            run_id, farm_id, total, auto_apply,
        )

        started = time.monotonic()

        async def on_sector_done(done: int, counts) -> None:
            await record_progress(run_id, done, counts)

        try:
            async with AsyncSessionLocal() as session:
                counts = await ProbeCalibrationService().compute_all_for_farm(
                    farm_id, session, auto_apply=auto_apply, on_sector_done=on_sector_done
                )
                await session.commit()
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.exception("Calibration sweep failed: run=%s farm=%s", run_id, farm_id)
            # Every exit path must reach a terminal status, or this farm keeps its
            # slot in the active-run unique index until staleness reclaims it.
            # preserve_counts: the tally died with the sweep, but the per-sector
            # progress writes already recorded what it managed to do — reporting
            # zeros here would hide bounds that really moved.
            await finish_run(
                run_id,
                CalibrationSweepCounts(),
                status="failure",
                error=str(exc),
                preserve_counts=True,
            )
            calibration_sweep_duration_seconds.observe(elapsed)
            calibration_sweep_total.labels("failure").inc()
            return

        elapsed = time.monotonic() - started
        outcome_status = "partial" if counts.failed else "success"
        await finish_run(run_id, counts, status=outcome_status)
        calibration_sweep_duration_seconds.observe(elapsed)
        calibration_sweep_total.labels(outcome_status).inc()
        per_sector = elapsed / total if total else 0.0
        logger.info(
            "Calibration sweep %s: run=%s farm=%s %.1fs total, %.2fs/sector — "
            "applied=%d skipped=%d no_candidate=%d candidates=%d failed=%d",
            outcome_status, run_id, farm_id, elapsed, per_sector,
            counts.applied, counts.skipped, counts.no_candidate,
            counts.candidates, counts.failed,
        )


async def _calibration_sweep_for_farm(farm, db):
    """One farm's calibration sweep, honouring its own auto-apply opt-in.

    Extracted from the job body so the flag-routing is testable without the
    scheduler, Redis lock, or a real trigger.

    Takes the same per-farm lock as the on-demand drain job, so a manual sweep
    and this one can never work the same farm at once.
    """
    from app.services.probe_calibration_service import (
        CalibrationSweepCounts,
        ProbeCalibrationService,
    )

    auto_apply = bool(getattr(farm, "calibration_auto_apply", False))

    async with JobLock(f"calibration_sweep:{farm.id}", ttl=3_600) as acquired:
        if not acquired:
            logger.info("Skipping farm %s — an on-demand sweep holds its lock", farm.id)
            return CalibrationSweepCounts()

        counts = await ProbeCalibrationService().compute_all_for_farm(
            str(farm.id), db, auto_apply=auto_apply
        )
    logger.info(
        "Probe calibration: farm=%s auto_apply=%s applied=%d skipped=%d "
        "no_candidate=%d candidates=%d failed=%d",
        farm.id,
        auto_apply,
        counts.applied,
        counts.skipped,
        counts.no_candidate,
        counts.candidates,
        counts.failed,
    )
    if counts.failed:
        logger.warning(
            "Probe calibration: farm=%s had %d sector failures",
            farm.id,
            counts.failed,
        )
    return counts


async def _run_recompute_probe_calibration() -> None:
    async def handle(farm, db) -> None:
        await _calibration_sweep_for_farm(farm, db)
        await db.commit()

    await _run_per_farm_job(
        job_name="probe_calibration",
        lock_name="probe_calibration",
        ttl=3_600,
        handle_farm=handle,
    )


async def _run_recompute_irrigation_fingerprint() -> None:
    from app.services.irrigation_fingerprint_service import (
        IrrigationFingerprintService,
    )

    svc = IrrigationFingerprintService()

    async def handle(farm, db) -> None:
        n = await svc.compute_all_for_farm(str(farm.id), db)
        await db.commit()
        logger.info("Irrigation fingerprint: farm=%s computed %d sectors", farm.id, n)

    await _run_per_farm_job(
        job_name="irrigation_fingerprint",
        lock_name="irrigation_fingerprint",
        ttl=3_600,
        handle_farm=handle,
    )


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")

    _scheduler.add_job(
        _run_alert_check,
        trigger=IntervalTrigger(hours=2),
        id="alert_check",
        replace_existing=True,
        misfire_grace_time=300,
    )
    _scheduler.add_job(
        _run_recommendation_generation,
        trigger=CronTrigger(hour=5, minute=0, timezone="UTC"),
        id="daily_recommendations",
        replace_existing=True,
        misfire_grace_time=600,
    )
    _scheduler.add_job(
        _run_data_ingestion,
        trigger=IntervalTrigger(minutes=15),
        id="data_ingestion",
        replace_existing=True,
        misfire_grace_time=120,
    )
    _scheduler.add_job(
        _run_flowmeter_ingestion,
        trigger=IntervalTrigger(minutes=20),
        id="flowmeter_ingestion",
        replace_existing=True,
        misfire_grace_time=120,
    )
    _scheduler.add_job(
        _run_reference_recompute,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0, timezone="UTC"),
        id="reference_recompute",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        _run_recompute_probe_calibration,
        trigger=CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="UTC"),
        id="probe_calibration",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        _run_recompute_irrigation_fingerprint,
        trigger=CronTrigger(day_of_week="mon", hour=4, minute=30, timezone="UTC"),
        id="irrigation_fingerprint",
        replace_existing=True,
        misfire_grace_time=300,
    )
    # max_instances=1 matters: without it APScheduler could start a second drain
    # tick while a multi-minute sweep is still running.
    _scheduler.add_job(
        _drain_calibration_sweep_queue,
        trigger=IntervalTrigger(seconds=10),
        id="calibration_sweep_drain",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    _scheduler.start()
    # Stamp an initial heartbeat so the worker healthcheck has a fresh value
    # immediately at boot, before the first interval job fires.
    record_heartbeat()
    logger.info("Scheduler started: %d jobs registered", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
