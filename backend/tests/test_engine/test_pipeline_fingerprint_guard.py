"""The dose-do-dia fingerprint lookup must never crash the recommendation.

A missing/broken `irrigation_fingerprint` table (e.g. migration lag on a fresh
deploy) previously raised out of the pipeline and 500'd every recommendation.
`_load_sector_fingerprint` isolates the query in a savepoint and degrades to
None so the dose simply falls back to mm_only.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.engine.pipeline import _load_sector_fingerprint


class _FakeSavepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False  # never suppress — let the error propagate to the guard


class _RowResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _RaisingSession:
    """Mimics asyncpg raising UndefinedTableError on the fingerprint SELECT."""

    def begin_nested(self):
        return _FakeSavepoint()

    async def execute(self, *args, **kwargs):
        raise RuntimeError('relation "irrigation_fingerprint" does not exist')


class _OkSession:
    def __init__(self, row):
        self._row = row

    def begin_nested(self):
        return _FakeSavepoint()

    async def execute(self, *args, **kwargs):
        return _RowResult(self._row)


async def test_db_error_degrades_to_none():
    assert await _load_sector_fingerprint(_RaisingSession(), "sector-1") is None


async def test_returns_row_when_present():
    sentinel = object()
    assert await _load_sector_fingerprint(_OkSession(sentinel), "sector-1") is sentinel


async def test_returns_none_when_absent():
    assert await _load_sector_fingerprint(_OkSession(None), "sector-1") is None


@pytest.fixture
async def real_db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def test_savepoint_leaves_real_session_writable_after_error(real_db):
    """The mechanism the whole guard relies on, proven against real Postgres.

    A genuine asyncpg error (missing relation) inside the begin_nested SAVEPOINT
    must roll back to the savepoint and leave the OUTER transaction usable — this
    is what lets recommendation_service's subsequent add/flush/commit succeed on
    the same session instead of failing with 'current transaction is aborted'.
    """
    # Mirror the guard's failure shape: a real error inside begin_nested.
    with pytest.raises(Exception):
        async with real_db.begin_nested():
            await real_db.execute(text('SELECT * FROM "irrigai_no_such_table_xyz"'))

    # The session must still accept queries/writes — exactly what the caller does next.
    val = (await real_db.execute(text("SELECT 1"))).scalar_one()
    assert val == 1
    await real_db.rollback()
