"""The run row's shape, and the partial unique index that makes duplicate
requests impossible across the 4 uvicorn processes."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import CalibrationSweepRun, Farm, User


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
    user = User(email=f"sweeprun-{stamp}@t.dev", name="SR", hashed_password="x", role="admin")
    db.add(user)
    await db.flush()
    farm = Farm(name=f"SR Farm {stamp}", owner_id=user.id)
    db.add(farm)
    await db.flush()
    return str(farm.id)


def test_table_and_index_names_registered():
    assert CalibrationSweepRun.__tablename__ == "calibration_sweep_run"
    cols = set(CalibrationSweepRun.__table__.columns.keys())
    assert {
        "id", "farm_id", "triggered_by_id", "status", "auto_apply",
        "sectors_total", "sectors_done",
        "applied", "skipped", "no_candidate", "candidates", "failed",
        "outcomes", "error",
        "queued_at", "started_at", "finished_at", "heartbeat_at",
    } <= cols
    index_names = {ix.name for ix in CalibrationSweepRun.__table__.indexes}
    assert "uq_calibration_sweep_run_active" in index_names


@pytest.mark.asyncio
async def test_defaults_are_zero_and_status_queued(db: AsyncSession):
    farm_id = await _farm(db)
    run = CalibrationSweepRun(farm_id=farm_id, auto_apply=True, queued_at=datetime.now(UTC))
    db.add(run)
    await db.flush()

    assert run.status == "queued"
    assert run.sectors_done == 0
    assert run.applied == 0 and run.failed == 0
    assert run.sectors_total is None
    assert run.outcomes is None
    await db.rollback()


@pytest.mark.asyncio
async def test_two_active_runs_for_one_farm_violate_the_unique_index(db: AsyncSession):
    """This is the guard that makes the API's 409 race-proof across processes."""
    farm_id = await _farm(db)
    now = datetime.now(UTC)
    db.add(CalibrationSweepRun(farm_id=farm_id, auto_apply=True, queued_at=now))
    await db.flush()

    db.add(CalibrationSweepRun(farm_id=farm_id, auto_apply=True, queued_at=now))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_a_terminal_run_does_not_block_a_new_one(db: AsyncSession):
    """stale/success are terminal, so they leave the index predicate — otherwise a
    dead run would lock the farm out forever."""
    farm_id = await _farm(db)
    now = datetime.now(UTC)
    for terminal in ("success", "stale", "failure", "partial"):
        db.add(CalibrationSweepRun(
            farm_id=farm_id, auto_apply=True, queued_at=now, status=terminal,
        ))
    await db.flush()

    db.add(CalibrationSweepRun(farm_id=farm_id, auto_apply=True, queued_at=now))
    await db.flush()   # must not raise

    rows = (await db.execute(
        select(CalibrationSweepRun).where(CalibrationSweepRun.farm_id == farm_id)
    )).scalars().all()
    assert len(rows) == 5
    await db.rollback()
