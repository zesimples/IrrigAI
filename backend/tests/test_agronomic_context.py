"""Tests for build_structured_agronomic_context.

The structured context is the LLM grounding surface — it must always contain a
stable set of keys so prompt templates can rely on JSON paths like
`probe_summary.latest_readings` regardless of how much data is present.
"""

from datetime import UTC

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.context_builder import (
    build_structured_agronomic_context,
    get_probe_diagnostics,
    get_sector_water_events,
)
from app.config import get_settings
from app.models import Farm, Plot, Probe, Sector


REQUIRED_TOP_LEVEL_KEYS = {
    "sector",
    "farm",
    "crop",
    "soil",
    "irrigation_system",
    "probe_summary",
    "water_events",
    "weather",
    "water_balance",
    "recommendation_history",
    "known_limitations",
    "confidence_inputs",
}

REQUIRED_PROBE_SUMMARY_KEYS = {"data_quality", "depths", "latest_readings", "diagnostics"}
REQUIRED_WEATHER_KEYS = {"recent_observations", "forecast"}
REQUIRED_CONFIDENCE_INPUTS_KEYS = {
    "fresh_depths",
    "total_depths",
    "stale_depths",
    "has_weather",
    "has_forecast",
    "has_water_balance",
    "active_water_events_14d",
    "irrigation_system_configured",
    "crop_profile_configured",
}


@pytest.fixture
async def async_db_session():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_sector_id(async_db_session: AsyncSession) -> str:
    farm = (
        await async_db_session.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))
    ).scalar_one()
    plot = (
        await async_db_session.execute(select(Plot).where(Plot.farm_id == farm.id))
    ).scalars().first()
    sector = (
        await async_db_session.execute(select(Sector).where(Sector.plot_id == plot.id))
    ).scalars().first()
    return sector.id


@pytest.mark.asyncio
async def test_structured_context_returns_required_keys(
    async_db_session: AsyncSession, seed_sector_id: str
):
    ctx = await build_structured_agronomic_context(seed_sector_id, async_db_session)
    assert "error" not in ctx
    assert REQUIRED_TOP_LEVEL_KEYS.issubset(ctx.keys()), (
        f"missing keys: {REQUIRED_TOP_LEVEL_KEYS - ctx.keys()}"
    )

    assert REQUIRED_PROBE_SUMMARY_KEYS.issubset(ctx["probe_summary"].keys())
    assert REQUIRED_WEATHER_KEYS.issubset(ctx["weather"].keys())
    assert REQUIRED_CONFIDENCE_INPUTS_KEYS.issubset(ctx["confidence_inputs"].keys())

    # Sector identity must round-trip
    assert ctx["sector"]["id"] == seed_sector_id

    # known_limitations is always a list (may be empty when everything is configured)
    assert isinstance(ctx["known_limitations"], list)


@pytest.mark.asyncio
async def test_structured_context_unknown_sector_returns_error(
    async_db_session: AsyncSession,
):
    ctx = await build_structured_agronomic_context(
        "00000000-0000-0000-0000-000000000000", async_db_session
    )
    assert ctx.get("error") == "sector_not_found"


@pytest.mark.asyncio
async def test_probe_diagnostics_shape(
    async_db_session: AsyncSession, seed_sector_id: str
):
    probe = (
        await async_db_session.execute(
            select(Probe).where(Probe.sector_id == seed_sector_id)
        )
    ).scalars().first()
    assert probe is not None
    diag = await get_probe_diagnostics(probe.id, async_db_session)
    assert "depths" in diag
    assert "last_ingestion_run" in diag
    assert diag["probe_id"] == probe.id


@pytest.mark.asyncio
async def test_water_events_returns_list(
    async_db_session: AsyncSession, seed_sector_id: str
):
    events = await get_sector_water_events(seed_sector_id, async_db_session, days=30)
    assert isinstance(events, list)
    for e in events:
        assert "kind" in e and "status" in e and "timestamp" in e
