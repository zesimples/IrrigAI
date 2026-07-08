"""API test: the probe readings endpoint surfaces a rootzone-weighted SWC overlay.

Regression coverage for the "Soma view looks green while the recommendation
reports high depletion" bug: the engine only ever sees the root-zone weighted
average, not a sum/average across all depths, so the chart now surfaces that
same weighted line (`rootzone_swc`) alongside the per-depth series.
"""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.probe_interpreter import _depth_interval_weights
from app.models import Farm, Plot, Probe, ProbeDepth, ProbeReading, Sector, SectorCropProfile, User
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"


@pytest.fixture
async def rootzone_probe(db: AsyncSession):
    """A VWC probe with two in-zone depths (root_depth_mature_m=0.6 → 60cm)."""
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()

    farm = Farm(name="Rootzone Series Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.30, wilting_point=0.10)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Rootzone Series Sector", crop_type="olive")
    db.add(sector)
    await db.flush()
    db.add(SectorCropProfile(
        sector_id=sector.id, crop_type="olive", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3, stages=[],
    ))
    probe = Probe(sector_id=sector.id, external_id="rootzone-series-probe")
    db.add(probe)
    await db.flush()

    depth_30 = ProbeDepth(probe_id=probe.id, depth_cm=30, sensor_type="soil_moisture")
    depth_60 = ProbeDepth(probe_id=probe.id, depth_cm=60, sensor_type="soil_moisture")
    depth_90 = ProbeDepth(probe_id=probe.id, depth_cm=90, sensor_type="soil_moisture")
    db.add_all([depth_30, depth_60, depth_90])
    await db.flush()

    now = datetime.now(UTC)
    ts = now - timedelta(hours=1)
    # In-zone depths (<=60cm) hold a dry value; the 90cm sensor (out of the 60cm
    # root zone) is wet and must NOT influence the rootzone average.
    db.add_all([
        ProbeReading(
            probe_depth_id=depth_30.id, timestamp=ts,
            raw_value=0.12, calibrated_value=0.12, unit="vwc_m3m3", quality_flag="ok",
        ),
        ProbeReading(
            probe_depth_id=depth_60.id, timestamp=ts,
            raw_value=0.18, calibrated_value=0.18, unit="vwc_m3m3", quality_flag="ok",
        ),
        ProbeReading(
            probe_depth_id=depth_90.id, timestamp=ts,
            raw_value=0.55, calibrated_value=0.55, unit="vwc_m3m3", quality_flag="ok",
        ),
    ])
    await db.commit()
    yield sector.id, probe.id
    await delete_farm_subtree(db, farm.id)


@pytest.mark.asyncio
async def test_rootzone_swc_present_and_hand_weighted(
    client: AsyncClient, db: AsyncSession, rootzone_probe
):
    sector_id, probe_id = rootzone_probe

    resp = await client.get(f"/api/v1/probes/{probe_id}/readings")
    assert resp.status_code == 200
    data = resp.json()

    assert data["root_depth_cm"] == pytest.approx(60.0)
    assert len(data["rootzone_swc"]) == 1

    weights = _depth_interval_weights([30, 60], 60.0)
    expected = round((weights[0] * 0.12 + weights[1] * 0.18) / sum(weights), 4)
    assert data["rootzone_swc"][0]["vwc"] == pytest.approx(expected, abs=1e-4)

    # The 90cm sensor is outside the 60cm root zone — the weighted value must
    # stay well below its wet 0.55 reading (this is the split-profile regression).
    assert data["rootzone_swc"][0]["vwc"] < 0.25


@pytest.mark.asyncio
async def test_rootzone_swc_empty_for_tension_only_probe(client: AsyncClient, db: AsyncSession):
    """Tension/Watermark probes have no VWC readings — rootzone_swc must be []
    but root_depth_cm should still be populated (calibration_available-style
    edge case from the brief)."""
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()

    farm = Farm(name="Rootzone Tension Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Tension Sector", crop_type="olive")
    db.add(sector)
    await db.flush()
    db.add(SectorCropProfile(
        sector_id=sector.id, crop_type="olive", mad=0.5,
        root_depth_mature_m=0.6, root_depth_young_m=0.3, stages=[],
    ))
    probe = Probe(sector_id=sector.id, external_id="rootzone-tension-probe")
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=30, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    db.add(ProbeReading(
        probe_depth_id=depth.id, timestamp=datetime.now(UTC) - timedelta(hours=1),
        raw_value=45.0, calibrated_value=None, unit="soil_tension_cbar", quality_flag="ok",
    ))
    await db.commit()

    try:
        resp = await client.get(f"/api/v1/probes/{probe.id}/readings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rootzone_swc"] == []
        assert data["root_depth_cm"] == pytest.approx(60.0)
    finally:
        await delete_farm_subtree(db, farm.id)
