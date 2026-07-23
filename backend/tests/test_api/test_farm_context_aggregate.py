"""Farm-summary aggregate context must reflect real irrigation/probe data.

Regression guard for the P4 farm-context change, which previously hardcoded
total_irrigation_7d_mm=0.0 / last_irrigation_date=None / a binary
source_confidence — telling the farm-summary LLM every sector applied nothing
and misreporting probe freshness.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context_builder import AssistantContextBuilder
from app.models import Farm, IrrigationEvent, Plot, Probe, Sector, User
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"


@pytest.fixture
async def farm_with_history(db: AsyncSession):
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    farm = Farm(name="History Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    irrigated = Sector(plot_id=plot.id, name="Irrigated Sector", crop_type="almond")
    dry = Sector(plot_id=plot.id, name="Dry Sector", crop_type="almond")
    db.add_all([irrigated, dry])
    await db.flush()

    now = datetime.now(UTC)
    db.add_all(
        [
            IrrigationEvent(
                sector_id=irrigated.id,
                start_time=now - timedelta(days=2),
                applied_mm=12.0,
                source="manual",
            ),
            IrrigationEvent(
                sector_id=irrigated.id,
                start_time=now - timedelta(days=1),
                applied_mm=8.0,
                source="manual",
            ),
            # 20 days old: counts for the last-irrigation date, NOT the 7-day total.
            IrrigationEvent(
                sector_id=irrigated.id,
                start_time=now - timedelta(days=20),
                applied_mm=99.0,
                source="manual",
            ),
        ]
    )
    # Fresh probe on the irrigated sector; the dry sector has none.
    db.add(
        Probe(
            sector_id=irrigated.id,
            external_id="hist/1",
            last_reading_at=now - timedelta(hours=2),
        )
    )
    await db.commit()
    yield {
        "farm_id": farm.id,
        "irrigated_id": irrigated.id,
        "dry_id": dry.id,
    }
    await delete_farm_subtree(db, farm.id)


@pytest.mark.asyncio
async def test_farm_sector_contexts_use_real_irrigation_and_probe_state(db, farm_with_history):
    contexts = await AssistantContextBuilder()._build_farm_sector_contexts(
        farm_with_history["farm_id"], db
    )
    by_id = {c.sector_id: c for c in contexts}
    irrigated = by_id[farm_with_history["irrigated_id"]]
    dry = by_id[farm_with_history["dry_id"]]

    # 7-day total excludes the 20-day-old event; last date reflects the newest event.
    assert irrigated.total_irrigation_7d_mm == 20.0
    assert irrigated.last_irrigation_date is not None
    assert irrigated.source_confidence == "fresh"

    # The dry sector genuinely applied nothing and has no probe — an honest zero,
    # not a fabricated one, and honestly "no_probe".
    assert dry.total_irrigation_7d_mm == 0.0
    assert dry.last_irrigation_date is None
    assert dry.source_confidence == "no_probe"
