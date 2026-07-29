"""The drain job: picks a queued run up, reports progress, finishes it —
and puts it back rather than failing it when the farm's lock is held."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.job_lock import JobLock
from app.models import (
    CalibrationSweepRun,
    Farm,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Sector,
    User,
)
from app.services.calibration_sweep_service import (
    QUEUE_KEY,
    enqueue_sweep,
    pop_queued_run_id,
)
from app.services.scheduler import _drain_calibration_sweep_queue


@pytest.fixture(autouse=True)
async def _test_isolation():
    """Same environment-only fixes as test_calibration_sweep_service.py.

    The drain job writes through `AsyncSessionLocal` (the process-wide engine,
    whose pooled connections end up bound to a closed loop under pytest-asyncio's
    per-test loops) and reaches Redis through two module-global clients cached
    forever — `calibration_sweep_service._redis` for the queue and
    `job_lock._redis` for the per-farm lock. Both idioms are correct in
    production, which has one event loop for the process lifetime. Resetting them
    per test is the test-only fix; the queue key is cleared so a stray id pushed
    by another test cannot be popped in place of this test's own.
    """
    import app.job_lock as job_lock
    import app.services.calibration_sweep_service as sweep_service
    from app.database import engine as shared_engine

    await shared_engine.dispose()
    sweep_service._redis = None
    job_lock._redis = None
    await sweep_service._get_redis().delete(QUEUE_KEY)
    yield


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _farm_with_sector(db: AsyncSession, *, auto_apply: bool) -> tuple[str, str]:
    """Farm→Plot→Sector→Probe→depth + 60 hourly VWC readings near 0.44.

    The plot's sandy_loam preset (FC 0.16) clamps a probe sitting near 0.44 —
    so the sweep has something real to apply.
    """
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"drain-{stamp}@t.dev", name="DR", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name=f"Drain Farm {stamp}", owner_id=user.id, calibration_auto_apply=auto_apply)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", soil_texture="sandy_loam",
                field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Talhão A3", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id=f"drain-{stamp}",
                  last_reading_at=datetime.now(UTC) - timedelta(hours=1))
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    base = datetime.now(UTC) - timedelta(hours=59)
    lo, hi = 0.41, 0.455
    for i in range(60):
        phase = i % 24
        frac = phase / 12
        tri = frac if frac <= 1 else (2 - frac)
        v = round(lo + (hi - lo) * tri, 4)
        db.add(ProbeReading(probe_depth_id=depth.id, timestamp=base + timedelta(hours=i),
                            raw_value=v, calibrated_value=v,
                            unit="vwc_m3m3", quality_flag="ok"))
    await db.flush()
    await db.commit()
    return str(farm.id), str(sector.id)


async def _cleanup(db: AsyncSession, farm_id: str) -> None:
    await db.execute(delete(CalibrationSweepRun).where(CalibrationSweepRun.farm_id == farm_id))
    farm = await db.get(Farm, farm_id)
    if farm is not None:
        owner_id = farm.owner_id
        await db.delete(farm)
        await db.flush()
        user = await db.get(User, owner_id)
        if user is not None:
            await db.delete(user)
    await db.commit()


@pytest.mark.asyncio
async def test_drain_runs_a_queued_sweep_to_success(db: AsyncSession):
    farm_id, _ = await _farm_with_sector(db, auto_apply=True)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        await _drain_calibration_sweep_queue()

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        assert fresh.status == "success"
        assert fresh.sectors_total == 1
        assert fresh.sectors_done == 1
        assert fresh.applied == 1
        assert fresh.started_at is not None and fresh.finished_at is not None
        assert len(fresh.outcomes) == 1
        assert fresh.outcomes[0]["reason"] == "applied"
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_drain_reports_progress_before_it_finishes(db: AsyncSession):
    """The progress write must land on its own session, or a poller sees 0/N for
    the whole ten minutes and then a jump to done."""
    farm_id, _ = await _farm_with_sector(db, auto_apply=True)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        await _drain_calibration_sweep_queue()

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        # heartbeat_at is only ever written by mark_running/record_progress/
        # finish_run, each on its own committed session.
        assert fresh.heartbeat_at is not None
        assert fresh.sectors_done == 1
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_drain_requeues_instead_of_failing_when_the_farm_lock_is_held(db: AsyncSession):
    """Monday's job holding the lock must not turn a valid request into a failure."""
    farm_id, _ = await _farm_with_sector(db, auto_apply=True)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        async with JobLock(f"calibration_sweep:{farm_id}", ttl=60) as acquired:
            assert acquired
            await _drain_calibration_sweep_queue()

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        assert fresh.status == "queued"        # untouched, not failed
        assert await pop_queued_run_id() == run_id   # and back on the queue
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_drain_finishes_the_run_even_when_the_sweep_raises(db: AsyncSession):
    """A failed sweep must reach a terminal status, or the farm stays wedged in
    the partial unique index until the staleness window expires."""
    farm_id, _ = await _farm_with_sector(db, auto_apply=True)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        from app.services.probe_calibration_service import (
            CalibrationSweepCounts,
            ProbeCalibrationService,
        )

        async def boom(_self, _farm_id, _db, *, auto_apply=False, on_sector_done=None):
            # Get one sector's worth of progress on the record, THEN die — the
            # realistic shape of a mid-sweep failure.
            partial = CalibrationSweepCounts(applied=1)
            partial.outcomes.append(object())     # only its length is read
            if on_sector_done is not None:
                await on_sector_done(1, partial)
            raise RuntimeError("sweep exploded")

        original = ProbeCalibrationService.compute_all_for_farm
        ProbeCalibrationService.compute_all_for_farm = boom
        try:
            await _drain_calibration_sweep_queue()      # must not raise
        finally:
            ProbeCalibrationService.compute_all_for_farm = original

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        assert fresh.status == "failure"
        assert fresh.finished_at is not None
        assert "sweep exploded" in (fresh.error or "")
        # The failure must not erase what the sweep already did to live bounds.
        assert fresh.sectors_done == 1
        assert fresh.applied == 1
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_drain_is_a_noop_on_an_empty_queue(db: AsyncSession):
    await _drain_calibration_sweep_queue()      # must not raise


@pytest.mark.asyncio
async def test_drain_marks_a_vanished_run_id_harmlessly(db: AsyncSession):
    """A queue entry whose row was deleted must not crash the job."""
    from app.services.calibration_sweep_service import requeue_run_id

    await requeue_run_id("00000000-0000-0000-0000-000000000000")
    await _drain_calibration_sweep_queue()      # must not raise
