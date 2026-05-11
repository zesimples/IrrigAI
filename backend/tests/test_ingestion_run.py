"""Tests for ProviderIngestionRun telemetry emitted by ingest_probe_readings.

These tests require the seeded DB (same as test_adapters.py); they assert that
each successful ingestion creates a ProviderIngestionRun row with non-empty
counters and the correct provider/source_type labelling.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.mock_probe import MockProbeProvider
from app.config import get_settings
from app.models import Probe, ProviderIngestionRun
from app.services.ingestion import ingest_probe_readings

NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


@pytest.fixture
async def async_db_session():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingestion_creates_run_record(async_db_session: AsyncSession):
    """Running ingest_probe_readings should insert a ProviderIngestionRun row."""
    probe_ext_id = "1044/4663"
    since = NOW - timedelta(hours=3)
    until = NOW

    # Resolve probe + farm so we can attribute the run record.
    probe = (
        await async_db_session.execute(
            select(Probe).where(Probe.external_id == probe_ext_id)
        )
    ).scalar_one_or_none()
    assert probe is not None, "seed data must include probe 1044/4663"

    # Walk up to the farm.
    from app.models import Plot, Sector
    sector = await async_db_session.get(Sector, probe.sector_id)
    plot = await async_db_session.get(Plot, sector.plot_id)
    farm_id = plot.farm_id

    provider = MockProbeProvider(soil_type="clay_loam", anomaly_rate=0.0)

    before_count = (
        await async_db_session.execute(
            select(ProviderIngestionRun).where(ProviderIngestionRun.probe_id == probe.id)
        )
    ).scalars().all()
    before_len = len(before_count)

    summary = await ingest_probe_readings(
        async_db_session, provider, probe_ext_id, since, until,
        farm_id=farm_id, provider_name="mock",
    )
    await async_db_session.commit()

    assert summary.run_id is not None, "run id should be returned in summary"

    after_runs = (
        await async_db_session.execute(
            select(ProviderIngestionRun)
            .where(ProviderIngestionRun.probe_id == probe.id)
            .order_by(ProviderIngestionRun.started_at.desc())
        )
    ).scalars().all()

    assert len(after_runs) == before_len + 1, "exactly one new run row expected"
    run = after_runs[0]
    assert run.provider == "mock"
    assert run.source_type == "probes"
    assert run.probe_external_id == probe_ext_id
    assert run.farm_id == farm_id
    assert run.requested_since is not None
    assert run.requested_until is not None
    assert run.latency_ms is not None and run.latency_ms >= 0
    assert run.status in ("success", "partial", "failed")
    assert run.provider_records_seen >= 0
    assert run.inserted == summary.inserted
    assert run.skipped_duplicate == summary.skipped_duplicate


@pytest.mark.asyncio
async def test_ingestion_run_records_failure(async_db_session: AsyncSession):
    """A probe external_id that does not exist must still emit a failed run."""
    bogus_id = "DOES-NOT-EXIST-9999"

    # We need a farm_id; pick the first seeded one.
    from app.models import Farm
    farm = (await async_db_session.execute(select(Farm))).scalars().first()
    assert farm is not None

    provider = MockProbeProvider(soil_type="clay_loam", anomaly_rate=0.0)
    summary = await ingest_probe_readings(
        async_db_session,
        provider,
        bogus_id,
        NOW - timedelta(hours=1),
        NOW,
        farm_id=farm.id,
        provider_name="mock",
    )

    # Unknown probe → errors but no insert; service still returns and logs a run.
    assert summary.inserted == 0
    assert summary.run_id is not None

    run = await async_db_session.get(ProviderIngestionRun, summary.run_id)
    assert run is not None
    assert run.probe_external_id == bogus_id
    # Probe row missing in DB → ingestion service marks the run failed
    # (adapter returned data but we had nowhere to land it).
    assert run.status == "failed"
    assert run.error_message is not None
