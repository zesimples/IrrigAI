"""Integration tests for the AnomalyDetector against seed DB data.

Requires Docker DB to be running with seed data loaded.
"""

import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.anomaly.detector import AnomalyDetector
from app.anomaly.rules.sensor_rules import Reading, detect_flatline, detect_impossible_value
from app.anomaly.types import Anomaly
from app.models import Farm, Plot, Probe, ProbeDepth, ProbeReading, Sector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seed_sector(db: AsyncSession) -> Sector:
    farm = (await db.execute(select(Farm).where(Farm.name == "Herdade do Esporão"))).scalar_one()
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm.id))).scalars().first()
    sector = (await db.execute(select(Sector).where(Sector.plot_id == plot.id))).scalars().first()
    return sector


# ---------------------------------------------------------------------------
# Clean seed data — expect no anomalies
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clean_seed_data_has_no_critical_anomalies(db: AsyncSession, seed_sector: Sector):
    """Seed data is clean — detector should not raise critical anomalies."""
    detector = AnomalyDetector()
    anomalies = await detector.detect_sector(seed_sector.id, db, lookback_hours=168)
    critical = [a for a in anomalies if a.severity == "critical"]
    assert critical == [], (
        f"Expected no critical anomalies in clean seed data, got: "
        f"{[(a.anomaly_type, a.depth_cm) for a in critical]}"
    )


@pytest.mark.asyncio
async def test_detector_returns_list(db: AsyncSession, seed_sector: Sector):
    detector = AnomalyDetector()
    result = await detector.detect_sector(seed_sector.id, db)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_detector_sorted_by_severity(db: AsyncSession, seed_sector: Sector):
    """Results should be sorted: critical first, then warning, then info."""
    detector = AnomalyDetector()
    anomalies = await detector.detect_sector(seed_sector.id, db, lookback_hours=168)
    if len(anomalies) < 2:
        pytest.skip("Not enough anomalies to verify sorting")

    order = {"critical": 0, "warning": 1, "info": 2}
    for i in range(len(anomalies) - 1):
        assert order[anomalies[i].severity] <= order[anomalies[i + 1].severity], (
            f"Anomalies not sorted: {anomalies[i].severity} before {anomalies[i+1].severity}"
        )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_same_key_deduped_to_one(self):
        detector = AnomalyDetector()
        ts = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
        a1 = Anomaly(
            anomaly_type="flatline", severity="warning", confidence=0.9,
            sector_id="s1", probe_id="p1", depth_cm=30, detected_at=ts,
            description_pt="x", description_en="x",
            likely_causes=(), recommended_actions=(),
        )
        a2 = Anomaly(
            anomaly_type="flatline", severity="critical", confidence=0.95,
            sector_id="s1", probe_id="p1", depth_cm=30, detected_at=ts,
            description_pt="y", description_en="y",
            likely_causes=(), recommended_actions=(),
        )
        result = detector._deduplicate([a1, a2])
        assert len(result) == 1
        # Critical should win
        assert result[0].severity == "critical"

    def test_different_depths_not_deduped(self):
        detector = AnomalyDetector()
        ts = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
        make = lambda depth, sev: Anomaly(
            anomaly_type="flatline", severity=sev, confidence=0.9,
            sector_id="s1", probe_id="p1", depth_cm=depth, detected_at=ts,
            description_pt="x", description_en="x",
            likely_causes=(), recommended_actions=(),
        )
        result = detector._deduplicate([make(10, "warning"), make(30, "warning")])
        assert len(result) == 2

    def test_different_types_not_deduped(self):
        detector = AnomalyDetector()
        ts = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
        make = lambda atype: Anomaly(
            anomaly_type=atype, severity="warning", confidence=0.9,
            sector_id="s1", probe_id="p1", depth_cm=30, detected_at=ts,
            description_pt="x", description_en="x",
            likely_causes=(), recommended_actions=(),
        )
        result = detector._deduplicate([make("flatline"), make("impossible_jump")])
        assert len(result) == 2

    def test_empty_list(self):
        detector = AnomalyDetector()
        assert detector._deduplicate([]) == []


# ---------------------------------------------------------------------------
# Injected anomalies via synthetic data
# ---------------------------------------------------------------------------

class TestInjectedAnomalies:
    def test_flatline_injection_detected(self):
        """Synthesize flatline data and verify detector finds it."""
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
        readings = [Reading(start + timedelta(hours=i), 0.25) for i in range(8)]
        anomalies = detect_flatline(readings, "sec", "prb", 30)
        assert len(anomalies) == 1
        assert anomalies[0].severity == "warning"

    def test_impossible_value_injection_detected(self):
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
        readings = [Reading(start, -0.05)]
        anomalies = detect_impossible_value(readings, "sec", "prb", 30)
        assert len(anomalies) == 1
        assert anomalies[0].severity == "critical"
        assert anomalies[0].confidence == 1.0

    def test_anomaly_has_bilingual_descriptions(self):
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
        readings = [Reading(start + timedelta(hours=i), 0.25) for i in range(8)]
        anomaly = detect_flatline(readings, "sec", "prb", 30)[0]
        assert len(anomaly.description_pt) > 10
        assert len(anomaly.description_en) > 10
        assert anomaly.description_pt != anomaly.description_en

    def test_anomaly_has_actionable_recommendations(self):
        start = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)
        readings = [Reading(start + timedelta(hours=i), 0.25) for i in range(8)]
        anomaly = detect_flatline(readings, "sec", "prb", 30)[0]
        assert len(anomaly.recommended_actions) >= 1
        assert len(anomaly.likely_causes) >= 1


# ---------------------------------------------------------------------------
# Confidence scoring integration
# ---------------------------------------------------------------------------

class TestConfidenceIntegration:
    def test_critical_anomaly_penalises_confidence_more(self):
        from app.engine.confidence import score
        from unittest.mock import MagicMock

        ts = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

        def make_anomaly(severity):
            return Anomaly(
                anomaly_type="flatline", severity=severity, confidence=0.9,
                sector_id="s1", probe_id="p1", depth_cm=30, detected_at=ts,
                description_pt="x", description_en="x",
                likely_causes=(), recommended_actions=(),
            )

        ctx = MagicMock()
        ctx.application_rate_mm_h = 2.5
        ctx.emitter_flow_lph = None
        ctx.phenological_stage = "mid_season"
        ctx.soil_texture = "clay_loam"
        ctx.field_capacity = 0.28
        ctx.defaults_used = []
        ctx.missing_config = []

        rz = MagicMock()
        rz.has_data = True
        rz.hours_since_any_reading = 1.0
        rz.all_depths_ok = True
        probes = MagicMock()
        probes.rootzone = rz
        probes.is_calibrated = True

        weather = MagicMock()
        weather.hours_since_observation = 2.0

        clean = score(ctx, probes, weather, anomalies=[])
        with_warning = score(ctx, probes, weather, anomalies=[make_anomaly("warning")])
        with_critical = score(ctx, probes, weather, anomalies=[make_anomaly("critical")])

        assert with_warning.score < clean.score
        assert with_critical.score < with_warning.score

    def test_info_only_anomaly_small_penalty(self):
        from app.engine.confidence import score
        from unittest.mock import MagicMock

        ts = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
        info_anomaly = Anomaly(
            anomaly_type="suspicious_repetition", severity="info", confidence=0.6,
            sector_id="s1", probe_id="p1", depth_cm=30, detected_at=ts,
            description_pt="x", description_en="x",
            likely_causes=(), recommended_actions=(),
        )

        ctx = MagicMock()
        ctx.application_rate_mm_h = 2.5
        ctx.emitter_flow_lph = None
        ctx.phenological_stage = "mid_season"
        ctx.soil_texture = "clay_loam"
        ctx.field_capacity = 0.28
        ctx.defaults_used = []
        ctx.missing_config = []

        rz = MagicMock()
        rz.has_data = True
        rz.hours_since_any_reading = 1.0
        rz.all_depths_ok = True
        probes = MagicMock()
        probes.rootzone = rz
        probes.is_calibrated = True

        weather = MagicMock()
        weather.hours_since_observation = 2.0

        clean = score(ctx, probes, weather, anomalies=[])
        with_info = score(ctx, probes, weather, anomalies=[info_anomaly])
        # Info anomaly → only -0.05 penalty (small)
        assert clean.score - with_info.score == pytest.approx(0.05, abs=0.001)
