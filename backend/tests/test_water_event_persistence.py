"""Tests for DetectedWaterEvent persistence and confirm/reject APIs.

Verifies:
- detect_and_persist_water_events is idempotent on (probe_id, timestamp, kind)
- POST /water-events/{id}/confirm transitions status → "confirmed"
- POST /water-events/{id}/reject  transitions status → "rejected"
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import DetectedWaterEvent, Farm, Plot, Probe, Sector
from app.services.water_event_service import detect_and_persist_water_events


@pytest.fixture
async def async_db_session():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def api_client():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.fixture
async def seed_probe_id(async_db_session: AsyncSession) -> str:
    farm = (
        await async_db_session.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))
    ).scalar_one()
    plot = (
        await async_db_session.execute(select(Plot).where(Plot.farm_id == farm.id))
    ).scalars().first()
    sector = (
        await async_db_session.execute(select(Sector).where(Sector.plot_id == plot.id))
    ).scalars().first()
    probe = (
        await async_db_session.execute(select(Probe).where(Probe.sector_id == sector.id))
    ).scalars().first()
    assert probe is not None
    return probe.id


@pytest.mark.asyncio
async def test_detect_and_persist_is_idempotent(
    async_db_session: AsyncSession, seed_probe_id: str
):
    """Running detection twice over the same window must not duplicate rows."""
    since = datetime.now(UTC) - timedelta(days=7)
    until = datetime.now(UTC)

    first = await detect_and_persist_water_events(
        seed_probe_id, async_db_session, since=since, until=until
    )
    await async_db_session.commit()

    second = await detect_and_persist_water_events(
        seed_probe_id, async_db_session, since=since, until=until
    )
    await async_db_session.commit()

    keys_first = {(e.probe_id, e.timestamp, e.kind) for e in first}
    keys_second = {(e.probe_id, e.timestamp, e.kind) for e in second}
    assert keys_first == keys_second

    db_rows = (
        await async_db_session.execute(
            select(DetectedWaterEvent).where(DetectedWaterEvent.probe_id == seed_probe_id)
        )
    ).scalars().all()
    db_keys = {(e.probe_id, e.timestamp, e.kind) for e in db_rows}
    assert keys_first.issubset(db_keys)


@pytest.mark.asyncio
async def test_confirm_and_reject_endpoints(
    api_client: AsyncClient,
    async_db_session: AsyncSession,
    seed_probe_id: str,
):
    """The confirm/reject endpoints must flip status correctly."""
    persisted = await detect_and_persist_water_events(
        seed_probe_id, async_db_session,
        since=datetime.now(UTC) - timedelta(days=7),
        until=datetime.now(UTC),
    )
    await async_db_session.commit()
    if not persisted:
        pytest.skip("No water events detected in seed data; cannot exercise confirm/reject.")

    target_id = persisted[0].id
    resp = await api_client.post(
        f"/api/v1/water-events/{target_id}/confirm", json={"notes": "Field-verified"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["notes"] == "Field-verified"

    resp = await api_client.post(
        f"/api/v1/water-events/{target_id}/reject", json={"notes": "Sensor glitch"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_list_water_events_endpoint(
    api_client: AsyncClient,
    async_db_session: AsyncSession,
    seed_probe_id: str,
):
    await detect_and_persist_water_events(
        seed_probe_id, async_db_session,
        since=datetime.now(UTC) - timedelta(days=7),
        until=datetime.now(UTC),
    )
    await async_db_session.commit()

    resp = await api_client.get(f"/api/v1/probes/{seed_probe_id}/water-events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
