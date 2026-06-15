import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.main import app


_TEST_CLEANUP_STATEMENTS = (
    "DELETE FROM recommendation_reason",
    "DELETE FROM detected_water_event",
    "DELETE FROM irrigation_event",
    "DELETE FROM recommendation",
    "DELETE FROM alert",
    "DELETE FROM sector_override",
    "DELETE FROM irrigation_event_detected",
    "DELETE FROM flowmeter_reading",
    "DELETE FROM provider_ingestion_run",
    "DELETE FROM provider_sync_log",
    "DELETE FROM weather_forecast",
    "DELETE FROM probe_reading WHERE timestamp >= TIMESTAMPTZ '2098-01-01'",
    """
    UPDATE probe_depth
    SET
        last_reading_at = NULL,
        last_quality_flag = NULL,
        last_unit = NULL,
        readings_count_total = 0,
        last_gap_detected_at = NULL,
        data_status = 'unknown'
    WHERE last_reading_at >= TIMESTAMPTZ '2098-01-01'
    """,
    "UPDATE probe SET last_reading_at = NULL WHERE last_reading_at >= TIMESTAMPTZ '2098-01-01'",
)


async def _cleanup_test_db() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            for statement in _TEST_CLEANUP_STATEMENTS:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def isolate_committed_db_rows():
    try:
        await _cleanup_test_db()
    except (OSError, OperationalError):
        # Some pure unit-test runs do not have PostgreSQL available.
        yield
        return

    try:
        yield
    finally:
        await _cleanup_test_db()


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
