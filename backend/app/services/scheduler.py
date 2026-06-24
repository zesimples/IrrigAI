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
from sqlalchemy import select

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
        from app.models import Farm

        logger.info("Scheduler: %s at %s", job_name, datetime.now(UTC))
        farms_ok = 0
        farms_failed = 0
        try:
            async for db in get_db():
                farms = (await db.execute(select(Farm))).scalars().all()
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

    async def handle(farm, db) -> None:
        await ingest_farm(farm.id, db, lookback_hours=4)

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
        from app.models import Farm
        from app.services.flowmeter_ingestion import (
            FlowmeterIngestionService,
            classify_flowmeter_run,
        )

        logger.info("Scheduler: flowmeter ingestion at %s", datetime.now(UTC))
        service = FlowmeterIngestionService()

        try:
            total_inserted = 0
            devices_ok = 0
            devices_failed = 0
            farms_failed = 0
            async for db in get_db():
                farms = (await db.execute(select(Farm))).scalars().all()
                for farm in farms:
                    try:
                        summary = await service.ingest_farm(farm.id, db)
                        total_inserted += summary.get("readings_inserted", 0)
                        devices_ok += summary.get("devices_succeeded", 0)
                        devices_failed += summary.get("devices_failed", 0)
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


async def _run_recompute_probe_calibration() -> None:
    from app.services.probe_calibration_service import ProbeCalibrationService

    svc = ProbeCalibrationService()

    async def handle(farm, db) -> None:
        n = await svc.compute_all_for_farm(str(farm.id), db)
        await db.commit()
        logger.info("Probe calibration: farm=%s calibrated %d sectors", farm.id, n)

    await _run_per_farm_job(
        job_name="probe_calibration",
        lock_name="probe_calibration",
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
