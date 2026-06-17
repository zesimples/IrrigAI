"""API test configuration.

Uses NullPool so each request creates a fresh asyncpg connection bound to the
current event loop — avoids the "Future attached to different loop" error when
pytest-asyncio gives each test function its own event loop.

The `db` fixture yields a direct AsyncSession for seeding data; committed rows
are visible to subsequent client requests (postgres MVCC).

Auth: the v1 API requires authentication on every endpoint and tenant ownership
on farm resources. The default `client` fixture authenticates as the demo seed
owner; `noauth_client` leaves `get_current_user` intact for tests that exercise
the real token flow (see test_auth_permissions.py).
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

# Seeded demo farms are owned by this user. Data-focused API tests should access
# those resources as the owning tenant, not as a cross-tenant fixture user.
_TEST_AUTH_EMAIL = "you@irrigai.dev"


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
async def noauth_client(settings):
    """HTTP client with only the DB dependency overridden — real auth still runs.

    Used by tests that drive the genuine token flow and assert 401/404 behaviour.
    """
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


@pytest.fixture
async def client(settings):
    """HTTP client authenticated as the seeded demo owner, DB overridden to NullPool."""
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
