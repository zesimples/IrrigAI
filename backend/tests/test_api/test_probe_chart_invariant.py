"""E2E invariant: the probe chart's reference lines use the SAME FC the engine uses.

Regression lock for the bug where GET /probes/{id}/readings built CC/PMP from the
plot preset while the recommendation engine used probe calibration — so a dry sector
looked saturated on the chart while the engine (correctly) said "irrigate". Both now
resolve FC through pipeline.resolve_sector_soil_bounds; this test fails if they ever
diverge again.
"""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.pipeline import build_sector_context
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


@pytest.fixture
async def calibrated_probe(db: AsyncSession):
    """An owned sector with a low plot preset FC (0.16) plus a calibration row (0.46).

    Returns (sector_id, probe_id). The preset and calibration deliberately disagree so
    the test proves the chart follows calibration, not the preset.
    """
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()

    farm = Farm(name="Chart Invariant Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Chart Invariant Sector", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id="chart-inv-probe")
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=10, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()
    now = datetime.now(UTC)
    for i in range(6):
        db.add(ProbeReading(
            probe_depth_id=depth.id,
            timestamp=now - timedelta(hours=i),
            raw_value=0.15, calibrated_value=0.15,
            unit="vwc_m3m3", quality_flag="ok",
        ))
    db.add(ProbeCalibration(
        sector_id=sector.id, observed_fc=0.46, observed_refill=0.30,
        method="envelope", num_cycles=0, consistency=0.5, window_days=60,
        computed_at=now,
    ))
    await db.commit()
    return sector.id, probe.id


@pytest.mark.asyncio
async def test_chart_reference_lines_match_engine_fc(
    client: AsyncClient, db: AsyncSession, calibrated_probe
):
    sector_id, probe_id = calibrated_probe

    resp = await client.get(f"/api/v1/probes/{probe_id}/readings")
    assert resp.status_code == 200
    rl = resp.json()["reference_lines"]

    # The chart must use the calibrated bounds, NOT the plot preset (0.16 / 0.07).
    assert rl["field_capacity"] == pytest.approx(0.46)
    assert rl["wilting_point"] == pytest.approx(0.30)

    # ...and they must equal exactly what the recommendation engine uses, so the
    # chart and the recommendation can never tell different stories.
    ctx = await build_sector_context(sector_id, db)
    assert rl["field_capacity"] == pytest.approx(ctx.field_capacity)
    assert rl["wilting_point"] == pytest.approx(ctx.wilting_point)
