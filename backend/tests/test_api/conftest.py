"""API test configuration.

Uses NullPool so each request creates a fresh asyncpg connection bound to the
current event loop — avoids the "Future attached to different loop" error when
pytest-asyncio gives each test function its own event loop.

The `db` fixture yields a direct AsyncSession for seeding data; committed rows
are visible to subsequent client requests (postgres MVCC).
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.database import get_db
from app.main import app


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture
async def db(settings):
    """Direct DB session for seeding test data before API calls."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(settings):
    """HTTP client with DB dependency overridden to use NullPool engine per test."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
