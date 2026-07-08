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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.user import User

# FK-safe teardown for fixtures that commit a farm subtree. The FKs are not
# ON DELETE CASCADE, so children must go first. Keeps API tests (which must
# commit so the client connection sees the data) from accumulating junk farms.
_FARM_SUBTREE_DELETES = (
    "DELETE FROM probe_reading WHERE probe_depth_id IN (SELECT pd.id FROM probe_depth pd "
    "JOIN probe p ON pd.probe_id=p.id JOIN sector s ON p.sector_id=s.id "
    "JOIN plot pl ON s.plot_id=pl.id WHERE pl.farm_id=:fid)",
    "DELETE FROM probe_calibration WHERE sector_id IN (SELECT s.id FROM sector s "
    "JOIN plot pl ON s.plot_id=pl.id WHERE pl.farm_id=:fid)",
    "DELETE FROM sector_crop_profile WHERE sector_id IN (SELECT s.id FROM sector s "
    "JOIN plot pl ON s.plot_id=pl.id WHERE pl.farm_id=:fid)",
    # recommendation_reason before recommendation before sector: PUT /crop-profile
    # now regenerates a recommendation on soil edits (see crop_profiles.py), so
    # fixtures that PUT soil changes leave behind recommendation rows too.
    "DELETE FROM recommendation_reason WHERE recommendation_id IN (SELECT r.id FROM recommendation r "
    "JOIN sector s ON r.sector_id=s.id JOIN plot pl ON s.plot_id=pl.id WHERE pl.farm_id=:fid)",
    "DELETE FROM recommendation WHERE sector_id IN (SELECT s.id FROM sector s "
    "JOIN plot pl ON s.plot_id=pl.id WHERE pl.farm_id=:fid)",
    "DELETE FROM probe_depth WHERE probe_id IN (SELECT p.id FROM probe p "
    "JOIN sector s ON p.sector_id=s.id JOIN plot pl ON s.plot_id=pl.id WHERE pl.farm_id=:fid)",
    "DELETE FROM probe WHERE sector_id IN (SELECT s.id FROM sector s "
    "JOIN plot pl ON s.plot_id=pl.id WHERE pl.farm_id=:fid)",
    "DELETE FROM sector WHERE plot_id IN (SELECT id FROM plot WHERE farm_id=:fid)",
    "DELETE FROM plot WHERE farm_id=:fid",
    "DELETE FROM farm WHERE id=:fid",
)


async def delete_farm_subtree(db: AsyncSession, farm_id: str) -> None:
    """Delete a farm and everything under it, children-first. Idempotent."""
    for stmt in _FARM_SUBTREE_DELETES:
        await db.execute(text(stmt), {"fid": farm_id})
    await db.commit()

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
