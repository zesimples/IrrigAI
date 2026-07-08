"""The dose-do-dia fingerprint lookup must never crash the recommendation.

A missing/broken `irrigation_fingerprint` table (e.g. migration lag on a fresh
deploy) previously raised out of the pipeline and 500'd every recommendation.
`_load_sector_fingerprint` isolates the query in a savepoint and degrades to
None so the dose simply falls back to mm_only.
"""
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
