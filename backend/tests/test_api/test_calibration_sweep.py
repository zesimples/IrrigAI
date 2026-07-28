"""POST /farms/{farm_id}/calibration-sweep — the manual farm-wide sweep."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Farm, Plot, Probe, ProbeDepth, ProbeReading, Sector, User

from .conftest import delete_farm_subtree

# The email the authenticated `client` fixture logs in as — the farm must be owned
# by this user or access.farm() correctly 404s.
_OWNER_EMAIL = "you@irrigai.dev"


async def _farm_with_calibratable_sector(
    db: AsyncSession, *, auto_apply: bool, stale_hours: float = 1.0
) -> tuple[str, str]:
    """Farm→Plot→Sector→Probe→depth + 60 hourly VWC readings near 0.44.

    The plot carries the sandy_loam preset (FC 0.16) that clamps a probe sitting
    near 0.44 — the bug auto-apply exists to fix.
    """
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
    plot = Plot(farm_id=farm.id, name="P", soil_texture="sandy_loam",
                field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Talhão A3", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id=f"sweep-{stamp}",
                  last_reading_at=datetime.now(UTC) - timedelta(hours=stale_hours))
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
    return str(farm.id), str(sector.id)


async def _teardown(db: AsyncSession, farm_id: str) -> None:
    """delete_farm_subtree does not cover audit_log (entity_id has no FK to farm,
    so a sweep's "probe_calibration_sweep_triggered" row would outlive the farm
    it references). probe_calibration_run rows DO get cleaned up implicitly:
    sector_id there is ON DELETE CASCADE, and delete_farm_subtree's raw DELETE
    FROM sector still triggers that DB-level cascade.
    """
    await db.execute(delete(AuditLog).where(AuditLog.entity_id == farm_id))
    await delete_farm_subtree(db, farm_id)
    await db.commit()


@pytest.mark.asyncio
async def test_unknown_farm_returns_404(client):
    resp = await client.post(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/calibration-sweep"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sweep_with_flag_on_applies_and_reports_the_transition(client, db: AsyncSession):
    farm_id, sector_id = await _farm_with_calibratable_sector(db, auto_apply=True)
    await db.commit()
    try:
        resp = await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")
        assert resp.status_code == 200
        body = resp.json()

        assert body["auto_apply"] is True
        assert body["counts"]["applied"] == 1
        assert len(body["outcomes"]) == 1
        o = body["outcomes"][0]
        assert o["sector_id"] == sector_id
        assert o["sector_name"] == "Talhão A3"
        assert o["reason"] == "applied"
        assert o["applied"] is True
        assert o["fc_before"] == pytest.approx(0.16)
        assert 0.43 <= o["fc_candidate"] <= 0.46
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_sweep_with_flag_off_records_candidates_only(client, db: AsyncSession):
    from app.models import ProbeCalibration

    farm_id, sector_id = await _farm_with_calibratable_sector(db, auto_apply=False)
    await db.commit()
    try:
        resp = await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")
        assert resp.status_code == 200
        body = resp.json()

        assert body["auto_apply"] is False
        assert body["counts"]["candidates"] == 1
        assert body["counts"]["applied"] == 0
        assert [o["reason"] for o in body["outcomes"]] == ["candidate"]

        # Nothing may reach the projection the engine reads.
        projection = (await db.execute(
            select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
        )).scalar_one_or_none()
        assert projection is None
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_blocked_sector_reports_reason_and_candidate(client, db: AsyncSession):
    farm_id, _ = await _farm_with_calibratable_sector(
        db, auto_apply=True, stale_hours=200.0
    )
    await db.commit()
    try:
        body = (await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")).json()

        assert body["counts"]["skipped"] == 1
        o = body["outcomes"][0]
        assert o["reason"] == "probe_stale"
        assert o["applied"] is False
        assert o["fc_candidate"] is not None   # measured, then withheld
    finally:
        await _teardown(db, farm_id)


@pytest.mark.asyncio
async def test_sweep_is_audited_with_the_triggering_user(client, db: AsyncSession):
    farm_id, _ = await _farm_with_calibratable_sector(db, auto_apply=True)
    await db.commit()
    try:
        await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")

        entries = (await db.execute(
            select(AuditLog).where(
                AuditLog.action == "probe_calibration_sweep_triggered",
                AuditLog.entity_id == farm_id,
            )
        )).scalars().all()
        assert len(entries) == 1
        # Unlike the scheduler's user_id=NULL rows, a manual sweep names its user.
        assert entries[0].user_id is not None
        assert entries[0].after_data["auto_apply"] is True
    finally:
        await _teardown(db, farm_id)
