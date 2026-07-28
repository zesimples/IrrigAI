"""Queue and run-row lifecycle for the background calibration sweep.

Why this module exists: the sweep takes 4.9–9.6 minutes on real farm data, which
outlives the frontend proxy's ~5-minute ceiling, so it cannot run on the request
path. The API queues a run here and the worker drains it.

Session discipline — the important part. The sweep itself runs inside one long
transaction that commits at the end. Progress written on THAT session would be
invisible to any poller until the sweep finished, so the progress/finish helpers
below open their own short-lived session and commit immediately. Progress is
telemetry, not part of the sweep's transaction.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import CalibrationSweepRun

logger = logging.getLogger(__name__)

QUEUE_KEY = "calibration_sweep_queue"

# A non-terminal run whose heartbeat (or queued_at, if never picked up) is older
# than this is presumed dead. Comfortably above the ~10 min worst case observed,
# and 30 minutes is the blast radius of a wedged farm.
SWEEP_STALE_MINUTES = 30

ACTIVE_STATUSES = ("queued", "running")

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    return _redis


class SweepAlreadyRunning(Exception):
    """A queued/running sweep already exists for this farm."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"sweep already active: {run_id}")
        self.run_id = run_id


def outcomes_to_json(counts) -> list[dict]:
    """SectorSweepOutcome dataclasses -> JSONB-ready dicts."""
    return [asdict(o) for o in counts.outcomes]


async def reclaim_stale_runs(db: AsyncSession, *, farm_id: str | None = None) -> int:
    """Mark cold non-terminal runs `stale`. Caller commits. Returns the count.

    `stale` is terminal, so this is also what frees a farm whose worker died:
    the row leaves the partial unique index and a new sweep can be queued.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=SWEEP_STALE_MINUTES)
    stmt = select(CalibrationSweepRun).where(
        CalibrationSweepRun.status.in_(ACTIVE_STATUSES),
        # queued rows have no heartbeat yet, so fall back to queued_at
        or_(
            CalibrationSweepRun.heartbeat_at < cutoff,
            CalibrationSweepRun.heartbeat_at.is_(None),
        ),
        CalibrationSweepRun.queued_at < cutoff,
    )
    if farm_id is not None:
        stmt = stmt.where(CalibrationSweepRun.farm_id == farm_id)

    rows = (await db.execute(stmt)).scalars().all()
    now = datetime.now(UTC)
    for row in rows:
        row.status = "stale"
        row.finished_at = now
        row.error = f"no heartbeat for more than {SWEEP_STALE_MINUTES} minutes"
        logger.warning("Calibration sweep run %s marked stale (farm=%s)", row.id, row.farm_id)
    if rows:
        await db.flush()
    return len(rows)


async def enqueue_sweep(
    farm_id: str,
    db: AsyncSession,
    *,
    auto_apply: bool,
    triggered_by_id: str | None,
) -> CalibrationSweepRun:
    """Insert a queued run and push its id. Caller commits.

    Raises SweepAlreadyRunning if one is active. The DB's partial unique index
    is the real guard — a pre-check alone would race across the 4 uvicorn
    processes — so we attempt the insert and translate the violation.
    """
    run = CalibrationSweepRun(
        farm_id=farm_id,
        auto_apply=auto_apply,
        triggered_by_id=triggered_by_id,
        status="queued",
        queued_at=datetime.now(UTC),
    )
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        active = (await db.execute(
            select(CalibrationSweepRun).where(
                CalibrationSweepRun.farm_id == farm_id,
                CalibrationSweepRun.status.in_(ACTIVE_STATUSES),
            ).order_by(CalibrationSweepRun.queued_at.desc()).limit(1)
        )).scalar_one_or_none()
        if active is None:
            # Not our unique-index violation (or the competing run finished
            # between the violation and this SELECT) — an empty run_id would
            # 409 the caller with nothing to poll. Surface the real error
            # instead of masquerading an unrelated/vanished conflict as
            # "already running".
            raise
        raise SweepAlreadyRunning(str(active.id)) from exc

    # Row first, queue second: a row with no queue entry goes stale and is
    # recoverable; a queue entry with no row is not.
    await _get_redis().lpush(QUEUE_KEY, str(run.id))
    return run


async def pop_queued_run_id() -> str | None:
    return await _get_redis().rpop(QUEUE_KEY)


async def requeue_run_id(run_id: str) -> None:
    """Put a run back because its farm's lock was held. Not a failure."""
    await _get_redis().lpush(QUEUE_KEY, run_id)


async def mark_running(run_id: str, sectors_total: int) -> None:
    async with AsyncSessionLocal() as session:
        now = datetime.now(UTC)
        result = await session.execute(
            update(CalibrationSweepRun)
            .where(CalibrationSweepRun.id == run_id)
            .values(
                status="running", started_at=now, heartbeat_at=now, sectors_total=sectors_total
            )
        )
        if result.rowcount == 0:
            logger.warning("mark_running: no CalibrationSweepRun row for id=%s", run_id)
        await session.commit()


async def record_progress(run_id: str, sectors_done: int, counts) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(CalibrationSweepRun)
            .where(CalibrationSweepRun.id == run_id)
            .values(
                sectors_done=sectors_done,
                heartbeat_at=datetime.now(UTC),
                applied=counts.applied,
                skipped=counts.skipped,
                no_candidate=counts.no_candidate,
                candidates=counts.candidates,
                failed=counts.failed,
            )
        )
        if result.rowcount == 0:
            logger.warning("record_progress: no CalibrationSweepRun row for id=%s", run_id)
        await session.commit()


async def finish_run(run_id: str, counts, *, status: str, error: str | None = None) -> None:
    async with AsyncSessionLocal() as session:
        now = datetime.now(UTC)
        result = await session.execute(
            update(CalibrationSweepRun)
            .where(CalibrationSweepRun.id == run_id)
            .values(
                status=status,
                finished_at=now,
                heartbeat_at=now,
                error=error,
                # Never let the final write snap progress backwards: the
                # failure path passes an empty CalibrationSweepCounts(), whose
                # len(outcomes) is 0 — a run that had polled to 34/77 must not
                # finish reporting 0/77. GREATEST is atomic (no read-then-write
                # race against a concurrent record_progress).
                sectors_done=func.greatest(
                    CalibrationSweepRun.sectors_done, len(counts.outcomes)
                ),
                applied=counts.applied,
                skipped=counts.skipped,
                no_candidate=counts.no_candidate,
                candidates=counts.candidates,
                failed=counts.failed,
                outcomes=outcomes_to_json(counts),
            )
        )
        if result.rowcount == 0:
            logger.warning("finish_run: no CalibrationSweepRun row for id=%s", run_id)
        await session.commit()
