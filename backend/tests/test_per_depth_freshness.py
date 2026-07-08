"""Tests for per-depth freshness state on ProbeDepth.

After a successful ingestion the matching ProbeDepth rows should have their
last_reading_at / last_quality_flag / last_unit / readings_count_total /
data_status fields populated by the ingestion service.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.mock_probe import MockProbeProvider
from app.config import get_settings
from app.models import Plot, Probe, ProbeDepth, Sector
from app.services.ingestion import _derive_data_status, ingest_probe_readings

NOW = datetime(2099, 1, 1, 12, tzinfo=UTC)


@pytest.fixture
async def async_db_session():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_derive_data_status_buckets():
    now = datetime(2026, 5, 11, 12, tzinfo=UTC)
    assert _derive_data_status(None, now) == "no_data"
    assert _derive_data_status(now - timedelta(hours=2), now) == "ok"
    # A ~20h daily-provider gap is fresh now (thresholds raised for daily providers).
    assert _derive_data_status(now - timedelta(hours=20), now) == "ok"
    assert _derive_data_status(now - timedelta(hours=40), now) == "partial"  # 30–72h
    assert _derive_data_status(now - timedelta(days=4), now) == "stale"      # >72h


@pytest.mark.asyncio
async def test_ingestion_updates_probe_depth_freshness(async_db_session: AsyncSession):
    probe_ext_id = "1044/4663"
    probe = (
        await async_db_session.execute(
            select(Probe).where(Probe.external_id == probe_ext_id)
        )
    ).scalar_one_or_none()
    assert probe is not None

    sector = await async_db_session.get(Sector, probe.sector_id)
    plot = await async_db_session.get(Plot, sector.plot_id)
    farm_id = plot.farm_id

    provider = MockProbeProvider(soil_type="clay_loam", anomaly_rate=0.0)
    since = NOW - timedelta(hours=3)
    until = NOW
    summary = await ingest_probe_readings(
        async_db_session, provider, probe_ext_id, since, until,
        farm_id=farm_id, provider_name="mock",
    )
    await async_db_session.commit()

    depths = (
        await async_db_session.execute(
            select(ProbeDepth).where(ProbeDepth.probe_id == probe.id)
        )
    ).scalars().all()
    assert depths, "probe should have at least one ProbeDepth"

    # At least one depth that received data must have a non-null last_reading_at
    # and a non-"unknown" data_status.
    touched = [d for d in depths if d.last_reading_at is not None]
    assert touched, "expected at least one depth to be updated by ingestion"

    for d in touched:
        assert d.last_reading_at is not None
        assert d.last_quality_flag in ("ok", "suspect", "invalid")
        assert d.last_unit is not None
        assert d.readings_count_total > 0
        assert d.data_status in ("ok", "partial", "stale", "no_data")
        # Freshly ingested rows whose latest timestamp is "now" must land in "ok"
        # since the mock provider emits up-to-the-minute readings.
        if (datetime.now(UTC) - d.last_reading_at).total_seconds() < 6 * 3600:
            assert d.data_status == "ok"
