"""Conftest for flowmeter API tests.

Uses NullPool so each request creates a fresh asyncpg connection bound to the
current event loop — avoids the "Future attached to different loop" error when
pytest-asyncio gives each test function its own event loop.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.user import User

# A dedicated user the auth override get-or-creates, so it exists regardless of
# which seed data the target DB happens to have (local demo seed vs. CI fresh DB).
_TEST_AUTH_EMAIL = "api-test-fixture@irrigai.test"


async def _get_or_create_test_user(session_factory) -> User:
    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == _TEST_AUTH_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=_TEST_AUTH_EMAIL,
                name="API Test Fixture",
                hashed_password="not-a-real-hash",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


@pytest.fixture
async def client():
    """HTTP client authenticated as a test user, DB overridden to NullPool."""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_current_user() -> User:
        return await _get_or_create_test_user(session_factory)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        await engine.dispose()
