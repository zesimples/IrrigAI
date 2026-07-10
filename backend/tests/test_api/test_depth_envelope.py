"""Per-depth observed envelope on /probes/{id}/readings.

Each depth with enough recent VWC history gets its own display-only CC/refill
(field_capacity/wilting_point on DepthReadings), derived from that depth's own
30-day envelope — so the Soma chart can sum real per-layer bounds instead of
stretching one per-depth value across all layers. Depths with too little data
stay null; a user-customized SCP (scp_override) suppresses the envelopes.
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
    ProbeDepth,
    ProbeReading,
    Sector,
    SectorCropProfile,
    User,
)
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"


def _tri_readings(depth_id: str, lo: float, hi: float, n: int = 60):
    """Hourly triangular wave between lo and hi ending now."""
    base = datetime.now(UTC) - timedelta(hours=n - 1)
    span = hi - lo
    rows = []
    for i in range(n):
        frac = (i % 24) / 12
        tri = frac if frac <= 1 else (2 - frac)
        v = round(lo + span * tri, 4)
        rows.append(ProbeReading(
            probe_depth_id=depth_id,
            timestamp=base + timedelta(hours=i),
            raw_value=v, calibrated_value=v,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    return rows


@pytest.fixture
async def envelope_probe(db: AsyncSession):
    """Probe with three depths: two with distinct 60-reading envelopes, one sparse."""
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    farm = Farm(name="Envelope Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.30, wilting_point=0.15)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Envelope Sector", crop_type="olive")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id="envelope-probe")
    db.add(probe)
    await db.flush()

    depths = {}
    for cm in (10, 30, 50):
        d = ProbeDepth(probe_id=probe.id, depth_cm=cm, sensor_type="soil_moisture")
        db.add(d)
        await db.flush()
        depths[cm] = d

    # Depth 10: wet layer 0.15–0.35; depth 30: dry layer 0.05–0.15.
    for r in _tri_readings(depths[10].id, 0.15, 0.35):
        db.add(r)
    for r in _tri_readings(depths[30].id, 0.05, 0.15):
        db.add(r)
    # Depth 50: too few readings for an envelope.
    for r in _tri_readings(depths[50].id, 0.10, 0.20, n=5):
        db.add(r)
    await db.commit()
    yield probe.id, sector.id
    await delete_farm_subtree(db, farm.id)


@pytest.mark.asyncio
async def test_per_depth_envelope_bounds(client: AsyncClient, envelope_probe):
    probe_id, _sector_id = envelope_probe
    resp = await client.get(f"/api/v1/probes/{probe_id}/readings")
    assert resp.status_code == 200
    by_cm = {d["depth_cm"]: d for d in resp.json()["depths"]}

    d10, d30, d50 = by_cm[10], by_cm[30], by_cm[50]
    # Each depth gets its own envelope: the wet layer's CC well above the dry one's.
    assert d10["field_capacity"] is not None and d30["field_capacity"] is not None
    assert d10["field_capacity"] > d30["field_capacity"]
    # Envelope ≈ [10th, 95th] percentile of that depth's own readings.
    assert 0.25 <= d10["field_capacity"] <= 0.36
    assert 0.14 <= d10["wilting_point"] <= 0.22
    assert 0.11 <= d30["field_capacity"] <= 0.16
    # Sparse depth: no envelope.
    assert d50["field_capacity"] is None and d50["wilting_point"] is None


@pytest.mark.asyncio
async def test_customized_scp_suppresses_depth_envelopes(
    client: AsyncClient, envelope_probe, db: AsyncSession
):
    """A deliberate manual soil override is authoritative — the chart must not
    show probe-derived envelopes against it."""
    probe_id, sector_id = envelope_probe
    scp = (
        await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
        )
    ).scalar_one_or_none()
    if scp is None:
        scp = SectorCropProfile(
            sector_id=sector_id, crop_type="olive", mad=0.5,
            root_depth_mature_m=0.8, root_depth_young_m=0.4, stages=[],
        )
        db.add(scp)
    scp.field_capacity = 0.30
    scp.wilting_point = 0.15
    scp.is_customized = True
    await db.commit()

    resp = await client.get(f"/api/v1/probes/{probe_id}/readings")
    assert resp.status_code == 200
    for d in resp.json()["depths"]:
        assert d["field_capacity"] is None and d["wilting_point"] is None
