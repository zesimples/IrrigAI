from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.active_records import get_active_sector
from app.config import get_settings
from app.models import Farm, Plot, Sector, User


@pytest.fixture
async def db():
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_active_sector_requires_active_complete_hierarchy(db: AsyncSession):
    suffix = datetime.now().timestamp()
    user = User(
        email=f"active-{suffix}@test.dev",
        name="Active",
        hashed_password="x",
    )
    db.add(user)
    await db.flush()
    farm = Farm(name="F", owner_id=user.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P")
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="S", crop_type="olive")
    db.add(sector)
    await db.flush()

    assert await get_active_sector(db, sector.id) is not None

    plot.is_archived = True
    await db.flush()
    assert await get_active_sector(db, sector.id) is None

    plot.is_archived = False
    farm.is_archived = True
    await db.flush()
    assert await get_active_sector(db, sector.id) is None

    farm.is_archived = False
    sector.is_archived = True
    await db.flush()
    assert await get_active_sector(db, sector.id) is None
