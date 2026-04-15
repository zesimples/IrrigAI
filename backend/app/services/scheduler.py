"""Background scheduler — APScheduler async jobs.

Jobs:
  - Alert check:              every 2 hours
  - Recommendation generation: daily at 05:00 (farm timezone)
  - Data ingestion:           every 30 minutes
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_alert_check() -> None:
    """Run alert engine for all farms."""
    from app.alerts.engine import AlertEngine
    from app.database import get_db
    from sqlalchemy import select
    from app.models import Farm

    logger.info("Scheduler: running alert check at %s", datetime.now(UTC))
    alert_engine = AlertEngine()

    async for db in get_db():
        try:
            farms_result = await db.execute(select(Farm))
            farms = farms_result.scalars().all()
            for farm in farms:
                try:
                    alerts = await alert_engine.run_farm_alerts(farm.id, db)
                    logger.info("Alert check: farm=%s generated/reconciled %d alerts", farm.id, len(alerts))
                except Exception:
                    logger.exception("Alert check failed for farm %s", farm.id)
        except Exception:
            logger.exception("Alert check job failed")


async def _run_recommendation_generation() -> None:
    """Generate daily recommendations for all farms."""
    from app.database import get_db
    from app.services.recommendation_service import generate_for_farm
    from sqlalchemy import select
    from app.models import Farm

    logger.info("Scheduler: generating daily recommendations at %s", datetime.now(UTC))

    async for db in get_db():
        try:
            farms_result = await db.execute(select(Farm))
            farms = farms_result.scalars().all()
            for farm in farms:
                try:
                    results = await generate_for_farm(farm.id, db)
                    logger.info("Recommendations: farm=%s generated %d", farm.id, len(results))
                except Exception:
                    logger.exception("Recommendation generation failed for farm %s", farm.id)
        except Exception:
            logger.exception("Daily recommendation job failed")


async def _run_data_ingestion() -> None:
    """Trigger data ingestion for all farms."""
    from app.database import get_db
    from app.services.ingestion import ingest_farm
    from sqlalchemy import select
    from app.models import Farm

    logger.info("Scheduler: data ingestion at %s", datetime.now(UTC))

    async for db in get_db():
        try:
            farms_result = await db.execute(select(Farm))
            farms = farms_result.scalars().all()
            for farm in farms:
                try:
                    await ingest_farm(farm.id, db, lookback_hours=4)
                except Exception:
                    logger.exception("Data ingestion failed for farm %s", farm.id)
        except Exception:
            logger.exception("Data ingestion job failed")


def start_scheduler() -> AsyncIOScheduler:
    """Start and return the APScheduler instance."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Alert check every 2 hours
    _scheduler.add_job(
        _run_alert_check,
        trigger=IntervalTrigger(hours=2),
        id="alert_check",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Daily recommendations at 05:00 UTC
    _scheduler.add_job(
        _run_recommendation_generation,
        trigger=CronTrigger(hour=5, minute=0, timezone="UTC"),
        id="daily_recommendations",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Data ingestion every 15 minutes
    _scheduler.add_job(
        _run_data_ingestion,
        trigger=IntervalTrigger(minutes=15),
        id="data_ingestion",
        replace_existing=True,
        misfire_grace_time=120,
    )

    _scheduler.start()
    logger.info("Scheduler started: %d jobs registered", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
