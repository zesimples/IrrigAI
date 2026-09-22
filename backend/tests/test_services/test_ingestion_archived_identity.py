"""Archived recovery copies must never capture live provider ingestion."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.dto import ProbeReadingDTO
from app.config import get_settings
from app.models import Farm, Plot, Probe, ProbeDepth, ProbeReading, Sector, User
from app.services.ingestion import ingest_probe_readings


@pytest.mark.asyncio
@pytest.mark.parametrize("archived_level", ["farm", "plot", "sector"])
async def test_ingestion_scopes_duplicate_external_ids_to_active_farm(monkeypatch, archived_level):
    engine = create_async_engine(get_settings().DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            user = User(email=f"recovery-{uuid4()}@test.dev", name="Recovery", hashed_password="x")
            db.add(user)
            await db.flush()
            external_id = f"recovery/{uuid4()}"
            records = []
            for index in range(3):
                farm = Farm(name=f"Farm {index}", owner_id=user.id)
                db.add(farm)
                await db.flush()
                plot = Plot(name="Plot", farm_id=farm.id)
                db.add(plot)
                await db.flush()
                sector = Sector(name="Sector", plot_id=plot.id, crop_type="olive")
                db.add(sector)
                await db.flush()
                probe = Probe(sector_id=sector.id, external_id=external_id)
                db.add(probe)
                await db.flush()
                depth = ProbeDepth(probe_id=probe.id, depth_cm=30, sensor_type="moisture")
                db.add(depth)
                if index == 0:
                    {"farm": farm, "plot": plot, "sector": sector}[
                        archived_level
                    ].is_archived = True
                records.append((farm, probe, depth))
            await db.flush()
            # The other active farm also owns this provider ID: farm scoping is essential.
            destination_farm, _, destination_depth = records[1]
            now = datetime(2099, 1, 1, tzinfo=UTC)
            provider = AsyncMock()
            provider.fetch_readings.return_value = [
                ProbeReadingDTO(
                    probe_external_id=external_id,
                    depth_cm=30,
                    timestamp=now,
                    raw_value=0.25,
                    unit="vwc_m3m3",
                    sensor_type="moisture",
                )
            ]
            # Separate audit transactions cannot see this test's uncommitted fixture.
            monkeypatch.setattr(
                "app.services.ingestion._persist_run_record", AsyncMock(return_value=None)
            )
            result = await ingest_probe_readings(
                db,
                provider,
                external_id,
                now - timedelta(hours=1),
                now,
                farm_id=destination_farm.id,
                provider_name="mock",
            )
            assert result.inserted == 1
            readings = (
                (
                    await db.execute(
                        select(ProbeReading).where(
                            ProbeReading.probe_depth_id.in_([depth.id for _, _, depth in records])
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [reading.probe_depth_id for reading in readings] == [destination_depth.id]
            assert records[0][1].last_reading_at is None
            # A direct attempt to ingest the archived hierarchy must insert nothing.
            archived_result = await ingest_probe_readings(
                db,
                provider,
                external_id,
                now - timedelta(hours=1),
                now,
                farm_id=records[0][0].id,
                provider_name="mock",
            )
            assert archived_result.inserted == 0
            assert archived_result.errors == 1
            await db.rollback()
    finally:
        await engine.dispose()
