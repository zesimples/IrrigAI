"""Integration test: ingest_farm must count per-device API failures.

Regression: when every MyIrrigation device POST returned 406 the per-device error
was swallowed inside ingest_device (return 0, None, None) and the run reported no
failures, so the scheduler logged "success". ingest_farm must surface
devices_failed / devices_succeeded so an all-failed run is observable.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.myirrigation import MyIrrigationAdapter
from app.config import get_settings
from app.models import Farm, Flowmeter, Plot, Sector, User
from app.services.flowmeter_ingestion import FlowmeterIngestionService


@pytest.fixture
async def db_session():
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _make_farm_with_flowmeters(db: AsyncSession, n: int) -> tuple[str, str]:
    user = User(
        email=f"fm-fail-{uuid.uuid4()}@irrigai.test", name="FM", hashed_password="x"
    )
    db.add(user)
    await db.flush()
    farm = Farm(name="FM Fail Farm", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="FM Plot")
    db.add(plot)
    await db.flush()
    for i in range(n):
        sector = Sector(plot_id=plot.id, name=f"FM Sector {i}", crop_type="olive")
        db.add(sector)
        await db.flush()
        db.add(
            Flowmeter(
                sector_id=sector.id,
                external_device_id=6990 + i,
                name=f"FM {i}",
                is_active=True,
            )
        )
    await db.commit()
    return farm.id, user.id


async def test_ingest_farm_counts_failed_devices(db_session, monkeypatch):
    farm_id, user_id = await _make_farm_with_flowmeters(db_session, n=3)
    try:
        adapter = MyIrrigationAdapter(
            base_url="http://x", username="u", password="p",
            client_id="c", client_secret="s",
        )

        async def _raise_406(*_args, **_kwargs):
            raise RuntimeError("406 Client Signature Invalid (simulated)")

        adapter._post_form_json = _raise_406
        monkeypatch.setattr(
            "app.adapters.factory.get_probe_provider",
            lambda settings, farm=None: adapter,
        )

        result = await FlowmeterIngestionService().ingest_farm(farm_id, db_session)

        assert result["readings_inserted"] == 0
        assert result["devices_failed"] == 3
        assert result["devices_succeeded"] == 0
    finally:
        farm = await db_session.get(Farm, farm_id)
        if farm is not None:
            await db_session.delete(farm)
        user = await db_session.get(User, user_id)
        if user is not None:
            await db_session.delete(user)
        await db_session.commit()
