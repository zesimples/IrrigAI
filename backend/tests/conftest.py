import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.limiter import limiter
from app.main import app

# Rate limiting uses a shared Redis counter that persists across tests (Redis is
# not reset between tests), so the accumulated count trips 429s late in the
# suite. No test asserts rate-limiting behaviour, so disable it process-wide.
limiter.enabled = False

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


# ---------------------------------------------------------------------------
# Minimal seed data for ingestion tests
# ---------------------------------------------------------------------------
# Several ingestion tests (test_adapters, test_ingestion_run,
# test_per_depth_freshness) use a raw async session and assume the canonical
# seed probes exist. CI runs against a freshly migrated, *unseeded* DB, so we
# create just those probes here. We deliberately create only the probes (+ their
# depth rows and FK chain) rather than the full demo farm, and own them with a
# dedicated fixture user, so empty-DB / per-user API tests are unaffected.
# The autouse cleanup above never deletes farm/plot/sector/probe/probe_depth/user
# rows, so this survives between tests and only needs to run once.

_SEED_USER_EMAIL = "seed-fixture@irrigai.test"
_SEED_PROBE_EXTERNAL_IDS = ("1044/4663", "1044/4664", "1044/4667")
_SEED_DEPTHS_CM = (10, 30, 60, 90)
_seed_done = False


async def _ensure_seed_probes() -> None:
    from app.models import Farm, Plot, Probe, ProbeDepth, Sector, User

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            existing = (
                await session.execute(
                    select(Probe).where(Probe.external_id == _SEED_PROBE_EXTERNAL_IDS[0])
                )
            ).scalar_one_or_none()
            if existing is not None:
                return

            user = User(
                email=_SEED_USER_EMAIL,
                name="Seed Fixture",
                hashed_password="not-a-real-hash",
            )
            session.add(user)
            await session.flush()

            farm = Farm(name="Seed Fixture Farm", owner_id=user.id)
            session.add(farm)
            await session.flush()

            plot = Plot(farm_id=farm.id, name="Seed Plot")
            session.add(plot)
            await session.flush()

            sector = Sector(plot_id=plot.id, name="Seed Sector", crop_type="olive")
            session.add(sector)
            await session.flush()

            for ext_id in _SEED_PROBE_EXTERNAL_IDS:
                probe = Probe(sector_id=sector.id, external_id=ext_id)
                session.add(probe)
                await session.flush()
                for depth in _SEED_DEPTHS_CM:
                    session.add(
                        ProbeDepth(probe_id=probe.id, depth_cm=depth, sensor_type="moisture")
                    )

            await session.commit()
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def seed_minimal_probe_data():
    global _seed_done
    if not _seed_done:
        try:
            await _ensure_seed_probes()
            _seed_done = True
        except (OSError, OperationalError):
            # Pure unit-test runs without PostgreSQL available.
            pass
    yield


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
