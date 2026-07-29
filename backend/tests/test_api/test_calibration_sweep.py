"""POST /farms/{id}/calibration-sweep now queues; GET polls the run.

The synchronous contract this file used to assert is gone: on real data the sweep
runs 4.9–9.6 minutes, which outlives the frontend proxy's ~5 minute ceiling, so
the endpoint queues a run and the worker does the work.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, CalibrationSweepRun, Farm, User
from app.services.calibration_sweep_service import (
    QUEUE_KEY,
    SWEEP_STALE_MINUTES,
    pop_queued_run_id,
)

from .conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"


@pytest.fixture(autouse=True)
async def _redis_isolation():
    """Same test-only fix as tests/test_engine/test_calibration_sweep_service.py.

    `_get_redis()` caches its client forever (the job_lock.py idiom, correct in
    production's single event loop); pytest-asyncio gives each test its own loop,
    so a client cached by an earlier test blows up with "attached to a different
    loop". Redis is also shared across the whole run, so a stray queued id from
    another test would be popped instead of this test's own.
    """
    import app.services.calibration_sweep_service as sweep_service

    sweep_service._redis = None
    await sweep_service._get_redis().delete(QUEUE_KEY)
    yield


async def _farm(db: AsyncSession, *, auto_apply: bool) -> str:
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    stamp = datetime.now(UTC).timestamp()
    farm = Farm(name=f"Sweep Farm {stamp}", owner_id=owner.id,
                calibration_auto_apply=auto_apply)
    db.add(farm)
    await db.flush()
    return str(farm.id)


async def _teardown(db: AsyncSession, farm_id: str) -> None:
    await db.execute(
        delete(CalibrationSweepRun).where(CalibrationSweepRun.farm_id == farm_id)
    )
    await delete_farm_subtree(db, farm_id)
    await db.commit()


@pytest.mark.asyncio
async def test_unknown_farm_returns_404(client):
    resp = await client.post(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/calibration-sweep"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_queues_a_run_and_returns_202(client, db: AsyncSession):
    farm_id = await _farm(db, auto_apply=True)
    await db.commit()
    try:
        resp = await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert body["auto_apply"] is True
        assert body["run_id"]

        # The row exists and the id was queued for the worker.
        run = await db.get(CalibrationSweepRun, body["run_id"])
        assert run is not None and run.status == "queued"
        assert await pop_queued_run_id() == body["run_id"]
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_post_echoes_the_farms_flag_and_never_overrides_it(client, db: AsyncSession):
    farm_id = await _farm(db, auto_apply=False)
    await db.commit()
    try:
        body = (await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")).json()
        assert body["auto_apply"] is False
        run = await db.get(CalibrationSweepRun, body["run_id"])
        assert run.auto_apply is False
        await pop_queued_run_id()
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_second_post_returns_409_with_the_active_run_id(client, db: AsyncSession):
    farm_id = await _farm(db, auto_apply=True)
    await db.commit()
    try:
        first = (await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")).json()

        resp = await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")
        assert resp.status_code == 409
        # The id lets the UI attach to the running sweep instead of just erroring.
        # Flat, NOT nested under FastAPI's `detail` envelope: the frontend reads
        # `body.run_id` straight off the parsed 409 body.
        assert resp.json()["run_id"] == first["run_id"]
        assert resp.json()["detail"]
        await pop_queued_run_id()
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_a_stale_run_is_reclaimed_so_a_new_sweep_can_start(client, db: AsyncSession):
    farm_id = await _farm(db, auto_apply=True)
    cold = datetime.now(UTC) - timedelta(minutes=SWEEP_STALE_MINUTES + 5)
    db.add(CalibrationSweepRun(
        farm_id=farm_id, auto_apply=True, queued_at=cold, status="running", heartbeat_at=cold,
    ))
    await db.commit()
    try:
        resp = await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")
        assert resp.status_code == 202

        rows = (await db.execute(
            select(CalibrationSweepRun).where(CalibrationSweepRun.farm_id == farm_id)
        )).scalars().all()
        statuses = sorted(r.status for r in rows)
        assert statuses == ["queued", "stale"]
        await pop_queued_run_id()
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_queueing_is_audited_with_the_triggering_user(client, db: AsyncSession):
    """Unlike the scheduler's user_id=NULL rows, a manual sweep names its user."""
    farm_id = await _farm(db, auto_apply=True)
    await db.commit()
    try:
        body = (await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")).json()

        entries = (await db.execute(
            select(AuditLog).where(
                AuditLog.action == "probe_calibration_sweep_queued",
                AuditLog.entity_id == farm_id,
            )
        )).scalars().all()
        assert len(entries) == 1
        assert entries[0].user_id is not None
        assert entries[0].after_data["auto_apply"] is True
        assert entries[0].after_data["run_id"] == body["run_id"]
        await pop_queued_run_id()
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_get_run_reports_progress_then_outcomes(client, db: AsyncSession):
    farm_id = await _farm(db, auto_apply=True)
    run = CalibrationSweepRun(
        farm_id=farm_id, auto_apply=True, queued_at=datetime.now(UTC),
        status="running", sectors_total=77, sectors_done=34, applied=5,
        heartbeat_at=datetime.now(UTC),
    )
    db.add(run)
    await db.commit()
    run_id = str(run.id)
    try:
        body = (await client.get(f"/api/v1/calibration-sweep-runs/{run_id}")).json()
        assert body["status"] == "running"
        assert body["sectors_total"] == 77
        assert body["sectors_done"] == 34
        assert body["counts"]["applied"] == 5
        assert body["outcomes"] is None          # not until terminal

        run.status = "success"
        run.outcomes = [{
            "sector_id": "s1", "sector_name": "Talhão A3", "reason": "applied",
            "applied": True, "fc_before": 0.16, "fc_candidate": 0.31,
            "refill_before": 0.07, "refill_candidate": 0.2,
            "method": "envelope", "before_source": "plot_preset",
        }]
        await db.commit()

        body = (await client.get(f"/api/v1/calibration-sweep-runs/{run_id}")).json()
        assert body["status"] == "success"
        assert len(body["outcomes"]) == 1
        assert body["outcomes"][0]["sector_name"] == "Talhão A3"
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_get_unknown_run_returns_404(client):
    resp = await client.get(
        "/api/v1/calibration-sweep-runs/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404
