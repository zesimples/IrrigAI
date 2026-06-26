"""API tests for the manual probe-calibration trigger.

POST /sectors/{sector_id}/auto-calibration/run computes and saves deterministic
soil bounds for one owned sector. Success returns the saved calibration metadata;
insufficient probe data returns 422. Ownership is enforced by Access.
"""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Farm,
    Plot,
    Probe,
    ProbeCalibration,
    ProbeDepth,
    ProbeReading,
    Sector,
    User,
)

_OWNER_EMAIL = "you@irrigai.dev"  # matches the authenticated client fixture in conftest


async def _owned_chain(db: AsyncSession, *, name: str) -> tuple[str, ProbeDepth]:
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    farm = Farm(name=f"{name} Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name=name, crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id=f"{name}-probe")
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    return sector.id, depth


@pytest.fixture
async def calibratable_sector(db: AsyncSession):
    """Owned sector with 60 gentle VWC readings → envelope calibration succeeds."""
    sector_id, depth = await _owned_chain(db, name="Calibratable")
    base = datetime.now(UTC) - timedelta(hours=59)
    lo, hi = 0.41, 0.455
    span = hi - lo
    for i in range(60):
        phase = i % 24
        frac = phase / 12
        tri = frac if frac <= 1 else (2 - frac)
        v = round(lo + span * tri, 4)
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=v, calibrated_value=v,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.commit()
    return sector_id


@pytest.fixture
async def insufficient_sector(db: AsyncSession):
    """Owned sector with a probe but too few readings to calibrate."""
    sector_id, depth = await _owned_chain(db, name="Insufficient")
    base = datetime.now(UTC) - timedelta(hours=5)
    for i in range(5):     # < CALIB_MIN_READINGS
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=0.44, calibrated_value=0.44,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.commit()
    return sector_id


@pytest.mark.asyncio
async def test_run_calibration_success(
    client: AsyncClient, db: AsyncSession, calibratable_sector
):
    sector_id = calibratable_sector

    resp = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sector_id"] == sector_id
    assert body["method"] == "envelope"
    assert 0.10 <= body["observed_fc"] <= 0.60
    assert body["observed_fc"] > body["observed_refill"]
    assert body["max_age_days"] == 90

    # Persisted exactly one row that recommendations will pick up.
    rows = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].observed_fc == pytest.approx(body["observed_fc"])


@pytest.mark.asyncio
async def test_run_calibration_is_idempotent_upsert(
    client: AsyncClient, db: AsyncSession, calibratable_sector
):
    sector_id = calibratable_sector

    r1 = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    r2 = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    assert r1.status_code == 200 and r2.status_code == 200

    rows = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalars().all()
    assert len(rows) == 1     # upsert, not duplicate


@pytest.mark.asyncio
async def test_run_calibration_insufficient_data_returns_422(
    client: AsyncClient, db: AsyncSession, insufficient_sector
):
    sector_id = insufficient_sector

    resp = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    assert resp.status_code == 422
    assert "nsufficient" in resp.json()["detail"]

    rows = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalars().all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_run_calibration_unknown_sector_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/sectors/00000000-0000-0000-0000-000000000000/auto-calibration/run"
    )
    assert resp.status_code == 404
