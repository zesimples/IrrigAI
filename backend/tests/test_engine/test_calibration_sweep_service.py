"""Queue + run-row lifecycle for the background sweep.

Progress/finish helpers deliberately open their OWN session and commit, because
the sweep itself runs in one long transaction — progress written on that session
would be invisible to pollers until the very end.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import CalibrationSweepRun, Farm, User
from app.services.calibration_sweep_service import (
    QUEUE_KEY,
    SWEEP_STALE_MINUTES,
    SweepAlreadyRunning,
    enqueue_sweep,
    finish_run,
    mark_running,
    outcomes_to_json,
    pop_queued_run_id,
    reclaim_stale_runs,
    record_progress,
    requeue_run_id,
)
from app.services.probe_calibration_service import CalibrationSweepCounts, SectorSweepOutcome


@pytest.fixture(autouse=True)
async def _test_isolation():
    """Two environment-only fixes, neither of which touches the module under test.

    1. mark_running/record_progress/finish_run use app.database.AsyncSessionLocal,
       the process-wide engine. pytest-asyncio gives each test its own event loop,
       but that engine's pool is created once at import time and normally lives
       for the whole process — under per-test loops its pooled asyncpg
       connections end up bound to a now-closed loop, so a later test's use of
       AsyncSessionLocal raises "attached to a different loop" errors that have
       nothing to do with this module's logic. Disposing forces fresh
       connections in the current loop. Never happens in production, which has
       exactly one event loop for its lifetime.
    2. `_get_redis()` mirrors job_lock.py's plain lazy-client idiom (create once,
       cache forever) — correct in production, which has exactly one event loop
       for the process lifetime. Under pytest-asyncio each test function gets
       its OWN event loop, so a client cached from an earlier test is bound to
       a now-closed loop and blows up with "attached to a different loop" on
       the next test that touches Redis. Resetting the module-global client
       before each test is the test-only fix for that; a loop-aware rebuild
       inside the module itself was tried and reverted (2nd review) because it
       leaked a connection pool per rebuild and made `_get_redis()` require a
       running loop, unlike the sibling it was meant to mirror.
    3. Redis is a real, shared instance across the whole test run (not reset
       per test). A couple of the tests below (`test_progress_is_visible_...`,
       `test_finish_run_...`) call `enqueue_sweep` — which pushes to the queue —
       without draining it, since draining isn't what they're testing. Left
       alone, that stray id sits ahead of whatever `test_requeue_puts_the_id_back`
       pushes and `pop_queued_run_id` returns the wrong one. Clearing the key
       before each test keeps the suite order-independent without changing what
       any individual test asserts.
    """
    import app.services.calibration_sweep_service as sweep_service
    from app.database import engine as shared_engine

    await shared_engine.dispose()
    sweep_service._redis = None
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


async def _farm(db: AsyncSession) -> str:
    stamp = datetime.now(UTC).timestamp()
    user = User(email=f"sweepsvc-{stamp}@t.dev", name="SS", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name=f"SS Farm {stamp}", owner_id=user.id)
    db.add(farm)
    await db.flush()
    await db.commit()          # the service helpers use their own sessions
    return str(farm.id)


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


def _counts(applied=1, outcomes=1) -> CalibrationSweepCounts:
    c = CalibrationSweepCounts(applied=applied)
    for i in range(outcomes):
        c.outcomes.append(SectorSweepOutcome(
            sector_id=f"00000000-0000-0000-0000-00000000000{i}",
            sector_name=f"Talhão {i}", reason="applied", applied=True,
            fc_before=0.16, fc_candidate=0.31,
            refill_before=0.07, refill_candidate=0.20,
            method="envelope", before_source="plot_preset",
        ))
    return c


@pytest.mark.asyncio
async def test_enqueue_creates_a_queued_run_and_pushes_the_id(db: AsyncSession):
    farm_id = await _farm(db)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()

        assert run.status == "queued"
        assert run.auto_apply is True
        assert run.queued_at is not None

        popped = await pop_queued_run_id()
        assert popped == str(run.id)
        assert await pop_queued_run_id() is None      # queue drained
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_second_enqueue_raises_with_the_active_run_id(db: AsyncSession):
    farm_id = await _farm(db)
    try:
        first = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        await pop_queued_run_id()

        with pytest.raises(SweepAlreadyRunning) as exc:
            await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        assert exc.value.run_id == str(first.id)
    finally:
        await db.rollback()
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_enqueue_with_unrelated_integrity_error_does_not_masquerade_as_already_running(
    db: AsyncSession,
):
    """A bad FK (or any non-unique-index violation) must not come back as
    SweepAlreadyRunning("") — that would 409 the caller with an empty run_id
    the UI then polls forever. It should surface as the real IntegrityError.
    """
    farm_id = await _farm(db)
    try:
        with pytest.raises(IntegrityError) as exc:
            await enqueue_sweep(
                farm_id,
                db,
                auto_apply=True,
                triggered_by_id="00000000-0000-0000-0000-000000000000",  # no such user
            )
        assert not isinstance(exc.value, SweepAlreadyRunning)
    finally:
        await db.rollback()
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_progress_is_visible_to_another_session_before_the_sweep_commits(db: AsyncSession):
    """The whole point of the separate session: a poller must see movement."""
    farm_id = await _farm(db)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        await mark_running(run_id, sectors_total=77)
        await record_progress(run_id, 34, _counts(applied=5, outcomes=34))

        # A DIFFERENT session — this is what the poll endpoint would see.
        settings = get_settings()
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as other:
            seen = await other.get(CalibrationSweepRun, run_id)
            assert seen.status == "running"
            assert seen.sectors_total == 77
            assert seen.sectors_done == 34
            assert seen.applied == 5
            assert seen.heartbeat_at is not None
        await engine.dispose()
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_finish_run_writes_terminal_status_and_outcomes(db: AsyncSession):
    farm_id = await _farm(db)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        await finish_run(run_id, _counts(applied=2, outcomes=2), status="success")

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        assert fresh.status == "success"
        assert fresh.finished_at is not None
        assert fresh.applied == 2
        assert len(fresh.outcomes) == 2
        assert fresh.outcomes[0]["sector_name"] == "Talhão 0"
        assert fresh.outcomes[0]["fc_candidate"] == 0.31
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_finish_run_does_not_snap_sectors_done_backwards_on_failure(db: AsyncSession):
    """The failure path calls finish_run with an empty CalibrationSweepCounts(),
    whose len(outcomes) is 0. A run that had already polled to 34/77 must keep
    reporting 34, not regress to 0 in the UI's last frame.
    """
    farm_id = await _farm(db)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        await mark_running(run_id, sectors_total=77)
        await record_progress(run_id, 34, _counts(applied=5, outcomes=34))

        await finish_run(run_id, CalibrationSweepCounts(), status="failure", error="boom")

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        assert fresh.status == "failure"
        assert fresh.error == "boom"
        assert fresh.sectors_done == 34
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_reclaim_marks_cold_non_terminal_runs_stale(db: AsyncSession):
    farm_id = await _farm(db)
    try:
        cold = datetime.now(UTC) - timedelta(minutes=SWEEP_STALE_MINUTES + 5)
        db.add(CalibrationSweepRun(
            farm_id=farm_id, auto_apply=True, queued_at=cold, status="running",
            heartbeat_at=cold,
        ))
        await db.flush()
        await db.commit()

        n = await reclaim_stale_runs(db, farm_id=farm_id)
        await db.commit()
        assert n == 1

        rows = (await db.execute(
            select(CalibrationSweepRun).where(CalibrationSweepRun.farm_id == farm_id)
        )).scalars().all()
        assert [r.status for r in rows] == ["stale"]

        # And because stale is terminal, a fresh run can now be queued.
        again = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        assert again.status == "queued"
        await pop_queued_run_id()
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_reclaim_leaves_a_warm_run_alone(db: AsyncSession):
    farm_id = await _farm(db)
    try:
        now = datetime.now(UTC)
        db.add(CalibrationSweepRun(
            farm_id=farm_id, auto_apply=True, queued_at=now, status="running", heartbeat_at=now,
        ))
        await db.flush()
        await db.commit()

        assert await reclaim_stale_runs(db, farm_id=farm_id) == 0
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_requeue_puts_the_id_back(db: AsyncSession):
    await requeue_run_id("11111111-1111-1111-1111-111111111111")
    assert await pop_queued_run_id() == "11111111-1111-1111-1111-111111111111"


def test_outcomes_to_json_is_plain_serialisable_dicts():
    payload = outcomes_to_json(_counts(outcomes=2))
    assert isinstance(payload, list) and len(payload) == 2
    assert payload[0]["reason"] == "applied"
    assert payload[0]["sector_name"] == "Talhão 0"
    import json
    json.dumps(payload)      # must not raise


@pytest.mark.asyncio
async def test_failed_finish_preserves_what_the_sweep_already_did(db: AsyncSession):
    """A sweep that dies half-way must not report `applied=0`.

    The drain job's failure path has no counts to hand — `compute_all_for_farm`
    raised, so its tally went with it — and used to pass an empty
    CalibrationSweepCounts(). That overwrote the numbers the per-sector progress
    writes had already recorded, so a run that moved real soil bounds on 5
    sectors finished claiming it applied nothing. `sectors_done` was guarded by
    GREATEST; the counters were not.
    """
    farm_id = await _farm(db)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        await mark_running(run_id, sectors_total=77)
        await record_progress(run_id, 34, _counts(applied=5, outcomes=34))

        await finish_run(
            run_id, CalibrationSweepCounts(), status="failure",
            error="boom", preserve_counts=True,
        )

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        assert fresh.status == "failure"
        assert fresh.error == "boom"
        assert fresh.finished_at is not None
        # What it actually did, not zeros.
        assert fresh.sectors_done == 34
        assert fresh.applied == 5
    finally:
        await _cleanup(db, farm_id)


@pytest.mark.asyncio
async def test_successful_finish_still_writes_the_final_tally(db: AsyncSession):
    """The preserve flag must not leak into the normal path."""
    farm_id = await _farm(db)
    try:
        run = await enqueue_sweep(farm_id, db, auto_apply=True, triggered_by_id=None)
        await db.commit()
        run_id = str(run.id)

        await mark_running(run_id, sectors_total=2)
        await record_progress(run_id, 1, _counts(applied=1, outcomes=1))
        await finish_run(run_id, _counts(applied=2, outcomes=2), status="success")

        db.expire_all()
        fresh = await db.get(CalibrationSweepRun, run_id)
        assert fresh.applied == 2
        assert fresh.sectors_done == 2
        assert len(fresh.outcomes) == 2
    finally:
        await _cleanup(db, farm_id)
