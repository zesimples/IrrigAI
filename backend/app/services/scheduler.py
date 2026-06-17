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
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.job_lock import JobLock
from app.metrics import scheduler_job_runs_total

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_alert_check() -> None:
    async with JobLock("alert_check", ttl=7_200) as acquired:
        if not acquired:
            scheduler_job_runs_total.labels("alert_check", "skipped").inc()
            return

        from app.alerts.engine import AlertEngine
        from app.database import get_db
        from app.models import Farm
        from sqlalchemy import select

        logger.info("Scheduler: alert check at %s", datetime.now(UTC))
        alert_engine = AlertEngine()

        try:
            async for db in get_db():
                try:
                    farms = (await db.execute(select(Farm))).scalars().all()
                    for farm in farms:
                        try:
                            alerts = await alert_engine.run_farm_alerts(farm.id, db)
                            logger.info("Alert check: farm=%s reconciled %d alerts", farm.id, len(alerts))
                        except Exception:
                            logger.exception("Alert check failed for farm %s", farm.id)
                except Exception:
                    logger.exception("Alert check job failed")
            scheduler_job_runs_total.labels("alert_check", "success").inc()
        except Exception:
            scheduler_job_runs_total.labels("alert_check", "failure").inc()
            raise


async def _run_recommendation_generation() -> None:
    async with JobLock("daily_recommendations", ttl=3_600) as acquired:
        if not acquired:
            scheduler_job_runs_total.labels("daily_recommendations", "skipped").inc()
            return

        from app.database import get_db
        from app.models import Farm
        from app.services.recommendation_service import generate_for_farm
        from sqlalchemy import select

        logger.info("Scheduler: daily recommendations at %s", datetime.now(UTC))

        try:
            async for db in get_db():
                try:
                    farms = (await db.execute(select(Farm))).scalars().all()
                    for farm in farms:
                        try:
                            results = await generate_for_farm(farm.id, db)
                            logger.info("Recommendations: farm=%s generated %d", farm.id, len(results))
                        except Exception:
                            logger.exception("Recommendation generation failed for farm %s", farm.id)
                except Exception:
                    logger.exception("Daily recommendation job failed")
            scheduler_job_runs_total.labels("daily_recommendations", "success").inc()
        except Exception:
            scheduler_job_runs_total.labels("daily_recommendations", "failure").inc()
            raise


async def _run_data_ingestion() -> None:
    async with JobLock("data_ingestion", ttl=900) as acquired:
        if not acquired:
            scheduler_job_runs_total.labels("data_ingestion", "skipped").inc()
            return

        from app.database import get_db
        from app.models import Farm
        from app.services.ingestion import ingest_farm
        from sqlalchemy import select

        logger.info("Scheduler: data ingestion at %s", datetime.now(UTC))

        try:
            async for db in get_db():
                try:
                    farms = (await db.execute(select(Farm))).scalars().all()
                    for farm in farms:
                        try:
                            await ingest_farm(farm.id, db, lookback_hours=4)
                        except Exception:
                            logger.exception("Data ingestion failed for farm %s", farm.id)
                except Exception:
                    logger.exception("Data ingestion job failed")
            scheduler_job_runs_total.labels("data_ingestion", "success").inc()
        except Exception:
            scheduler_job_runs_total.labels("data_ingestion", "failure").inc()
            raise


async def _run_flowmeter_ingestion() -> None:
    async with JobLock("flowmeter_ingestion", ttl=1_200) as acquired:
        if not acquired:
            scheduler_job_runs_total.labels("flowmeter_ingestion", "skipped").inc()
            return

        from app.database import get_db
        from app.metrics import flowmeter_device_ingestion_total
        from app.models import Farm
        from app.services.flowmeter_ingestion import (
            FlowmeterIngestionService,
            classify_flowmeter_run,
        )
        from sqlalchemy import select

        logger.info("Scheduler: flowmeter ingestion at %s", datetime.now(UTC))
        service = FlowmeterIngestionService()

        try:
            total_inserted = 0
            devices_ok = 0
            devices_failed = 0
            async for db in get_db():
                try:
                    farms = (await db.execute(select(Farm))).scalars().all()
                    for farm in farms:
                        try:
                            summary = await service.ingest_farm(farm.id, db)
                            total_inserted += summary.get("readings_inserted", 0)
                            devices_ok += summary.get("devices_succeeded", 0)
                            devices_failed += summary.get("devices_failed", 0)
                        except Exception:
                            logger.exception(
                                "Flowmeter ingestion failed for farm %s", farm.id
                            )
                        try:
                            from app.alerts.flowmeter_flow_rate_alerts import FlowmeterFlowRateAlertChecker
                            await FlowmeterFlowRateAlertChecker().check_and_persist(str(farm.id), db)
                        except Exception:
                            logger.exception(
                                "Flow-rate alert check failed for farm %s", farm.id
                            )
                except Exception:
                    logger.exception("Flowmeter ingestion job failed")
            if devices_ok:
                flowmeter_device_ingestion_total.labels("success").inc(devices_ok)
            if devices_failed:
                flowmeter_device_ingestion_total.labels("failure").inc(devices_failed)
            # Record the real outcome: an all-devices-failed run (e.g. 406 on every
            # device) is a failure, not a success — even though the job didn't raise.
            status = classify_flowmeter_run(total_inserted, devices_failed)
            scheduler_job_runs_total.labels("flowmeter_ingestion", status).inc()
        except Exception:
            scheduler_job_runs_total.labels("flowmeter_ingestion", "failure").inc()
            raise


async def _run_reference_recompute() -> None:
    async with JobLock("reference_recompute", ttl=3_600) as acquired:
        if not acquired:
            scheduler_job_runs_total.labels("reference_recompute", "skipped").inc()
            return

        from app.database import get_db
        from app.models import Farm
        from app.services.flowmeter_reference import FlowmeterReferenceService
        from sqlalchemy import select

        logger.info("Scheduler: reference recompute at %s", datetime.now(UTC))
        svc = FlowmeterReferenceService()

        try:
            async for db in get_db():
                try:
                    farms = (await db.execute(select(Farm))).scalars().all()
                    for farm in farms:
                        try:
                            await svc.compute_all_for_farm(str(farm.id), db)
                            await db.commit()
                        except Exception:
                            logger.exception("Reference recompute failed for farm %s", farm.id)
                except Exception:
                    logger.exception("Reference recompute job failed")
            scheduler_job_runs_total.labels("reference_recompute", "success").inc()
        except Exception:
            scheduler_job_runs_total.labels("reference_recompute", "failure").inc()
            raise


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

    _scheduler.start()
    logger.info("Scheduler started: %d jobs registered", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
