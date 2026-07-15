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
    ProbeCalibrationRun,
    ProbeDepth,
    ProbeReading,
    Sector,
    SectorCropProfile,
    User,
)
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"  # matches the authenticated client fixture in conftest


async def _owned_chain(db: AsyncSession, *, name: str) -> tuple[str, str, ProbeDepth]:
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
    return farm.id, sector.id, depth


@pytest.fixture
async def calibratable_sector(db: AsyncSession):
    """Owned sector with 60 gentle VWC readings → envelope calibration succeeds."""
    farm_id, sector_id, depth = await _owned_chain(db, name="Calibratable")
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
    yield sector_id
    await delete_farm_subtree(db, farm_id)


@pytest.fixture
async def insufficient_sector(db: AsyncSession):
    """Owned sector with a probe but too few readings to calibrate."""
    farm_id, sector_id, depth = await _owned_chain(db, name="Insufficient")
    base = datetime.now(UTC) - timedelta(hours=5)
    for i in range(5):     # < CALIB_MIN_READINGS
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=0.44, calibrated_value=0.44,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    await db.commit()
    yield sector_id
    await delete_farm_subtree(db, farm_id)


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
    # Before this run the sector used the plot preset (0.16); after, the calibration.
    assert body["previous_fc"] == pytest.approx(0.16)
    assert body["changed"] is True
    assert body["cleared_customization"] is False     # nothing was customized
    # No override → the calibration is what the engine will use.
    assert body["applied"] is True
    assert body["effective_source"] == "probe_calibrated"
    assert body["effective_fc"] == pytest.approx(body["observed_fc"])

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

    # First run is a fresh calibration; re-running on the same data reports no change.
    assert r1.json()["changed"] is True
    b2 = r2.json()
    assert b2["changed"] is False
    assert b2["previous_fc"] == pytest.approx(r1.json()["observed_fc"])

    history_response = await client.get(
        f"/api/v1/sectors/{sector_id}/calibration-runs"
    )
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 2
    assert {row["status"] for row in history} == {"applied", "superseded"}

    rows = (await db.execute(
        select(ProbeCalibrationRun).where(ProbeCalibrationRun.sector_id == sector_id)
    )).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_run_calibration_overrides_customization(
    client: AsyncClient, db: AsyncSession, calibratable_sector
):
    """Recency rule: pressing the button overrides a prior manual soil
    customization — it clears is_customized so the calibration takes effect."""
    sector_id = calibratable_sector
    db.add(SectorCropProfile(
        sector_id=sector_id, crop_type="almond", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3,
        field_capacity=0.171, wilting_point=0.089, stages=[], is_customized=True,
    ))
    await db.commit()

    resp = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    assert resp.status_code == 200
    body = resp.json()
    # The customization was cleared and the calibration is now authoritative.
    assert body["cleared_customization"] is True
    assert body["applied"] is True
    assert body["effective_source"] == "probe_calibrated"
    assert body["effective_fc"] == pytest.approx(body["observed_fc"])
    assert body["previous_fc"] == pytest.approx(0.171)   # what it used before
    assert body["changed"] is True

    # And the SCP customization flag is actually off now, so the engine uses calib.
    scp = (await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
    )).scalar_one()
    assert scp.is_customized is False


@pytest.mark.asyncio
async def test_manual_edit_overrides_calibration_after(
    client: AsyncClient, db: AsyncSession, calibratable_sector
):
    """The other half of the recency rule: a manual CC/PMP edit AFTER calibration
    re-customizes the sector and overrides the calibration again."""
    sector_id = calibratable_sector
    # Sectors normally have an (auto-created) crop profile; the fixture doesn't, so
    # add a non-customized one for the manual-edit endpoint to update.
    db.add(SectorCropProfile(
        sector_id=sector_id, crop_type="almond", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3,
        field_capacity=0.16, wilting_point=0.07, stages=[], is_customized=False,
    ))
    await db.commit()

    await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")

    # Manual edit via the crop-profile endpoint re-customizes the sector.
    resp = await client.put(
        f"/api/v1/sectors/{sector_id}/crop-profile",
        json={"field_capacity": 0.20, "wilting_point": 0.10},
    )
    assert resp.status_code == 200

    scp = (await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
    )).scalar_one()
    assert scp.is_customized is True          # manual edit overrides calibration again

    # Confirming the recency loop: a fresh calibration run would again clear it.
    rerun = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    assert rerun.json()["cleared_customization"] is True


@pytest.mark.asyncio
async def test_run_calibration_insufficient_data_returns_422(
    client: AsyncClient, db: AsyncSession, insufficient_sector
):
    sector_id = insufficient_sector

    resp = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    assert resp.status_code == 422
    # Honest, specific reason: not enough VWC readings (names the 48 threshold).
    detail = resp.json()["detail"]
    assert "48" in detail and "VWC" in detail

    rows = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalars().all()
    assert len(rows) == 0


@pytest.fixture
async def tension_sector(db: AsyncSession):
    """Owned sector whose only probe is a tension (Watermark) sensor — no VWC."""
    farm_id, sector_id, depth = await _owned_chain(db, name="Tension")
    # _owned_chain made a soil_moisture depth; convert this one to tension instead
    # so the sector has no VWC depth at all.
    depth.sensor_type = "soil_tension"
    base = datetime.now(UTC) - timedelta(hours=59)
    for i in range(60):
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=base + timedelta(hours=i),
            raw_value=35.0, calibrated_value=35.0,
            unit="soil_tension_cbar", quality_flag="ok",
        ))
    await db.commit()
    yield sector_id
    await delete_farm_subtree(db, farm_id)


@pytest.mark.asyncio
async def test_run_calibration_tension_only_explains_sensor_type(
    client: AsyncClient, db: AsyncSession, tension_sector
):
    sector_id = tension_sector

    resp = await client.post(f"/api/v1/sectors/{sector_id}/auto-calibration/run")
    assert resp.status_code == 422
    # The user must learn it's a sensor-type issue, not a data-volume issue.
    detail = resp.json()["detail"].lower()
    assert "tensão" in detail or "watermark" in detail

    rows = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalars().all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_status_calibration_available_true_for_vwc(
    client: AsyncClient, calibratable_sector
):
    resp = await client.get(f"/api/v1/sectors/{calibratable_sector}/status")
    assert resp.status_code == 200
    assert resp.json()["calibration_available"] is True


@pytest.mark.asyncio
async def test_status_includes_plot_fields(
    client: AsyncClient, calibratable_sector, db: AsyncSession
):
    """Status carries the sector's plot id + name (breadcrumb needs them)."""
    resp = await client.get(f"/api/v1/sectors/{calibratable_sector}/status")
    assert resp.status_code == 200
    body = resp.json()
    sector = (
        await db.execute(select(Sector).where(Sector.id == calibratable_sector))
    ).scalar_one()
    assert body["plot_id"] == sector.plot_id
    assert body["plot_name"] == "P"


@pytest.fixture
async def cyclic_sector(db: AsyncSession):
    """Owned sector with a clean irrigation sawtooth on a "soil_moisture" depth:
    4 sharp rises (>3 vol% within one 2h step) each followed by a slow decay —
    enough cycles + readings for the legacy preview analysis."""
    farm_id, sector_id, depth = await _owned_chain(db, name="Cyclic")
    start = datetime.now(UTC) - timedelta(days=28)
    ts = start
    v = 0.30
    for _cycle in range(4):
        v = 0.38  # irrigation spike
        for _ in range(80):  # ~6.7 days of 2h-step decay
            db.add(ProbeReading(
                probe_depth_id=depth.id,
                timestamp=ts,
                raw_value=round(v, 4), calibrated_value=round(v, 4),
                unit="vwc_m3m3", quality_flag="ok",
            ))
            ts += timedelta(hours=2)
            v = max(v - 0.001, 0.29)
    await db.commit()
    yield sector_id
    await delete_farm_subtree(db, farm_id)


@pytest.mark.asyncio
async def test_preview_sees_soil_moisture_sectors(
    client: AsyncClient, cyclic_sector
):
    """GET /auto-calibration (preview) must accept real VWC depths
    (sensor_type "soil_moisture") — it used to match only the legacy
    "moisture" and 404'd every real sector while /run worked."""
    resp = await client.get(f"/api/v1/sectors/{cyclic_sector}/auto-calibration")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["observed"]["num_cycles"] >= 3


@pytest.mark.asyncio
async def test_status_calibration_available_false_for_tension(
    client: AsyncClient, tension_sector
):
    resp = await client.get(f"/api/v1/sectors/{tension_sector}/status")
    assert resp.status_code == 200
    assert resp.json()["calibration_available"] is False


@pytest.mark.asyncio
async def test_run_calibration_unknown_sector_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/sectors/00000000-0000-0000-0000-000000000000/auto-calibration/run"
    )
    assert resp.status_code == 404
