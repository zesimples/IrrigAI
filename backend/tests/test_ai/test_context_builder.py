"""Tests for context builder — verifies shape and serializability.

These tests use the dataclass structure directly without a DB (unit tests).
Integration tests (with a real DB) should use the fixtures in tests/fixtures/.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.ai.context_builder import (
    AssistantContextBuilder,
    FarmAssistantContext,
    SectorAssistantContext,
    _farm_probe_confidence,
    _recommendation_snapshot_context,
)

_NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def test_farm_probe_confidence_no_probe_configured():
    confidence, explanation = _farm_probe_confidence(
        has_probe=False, last_reading_at=None, now=_NOW
    )
    assert confidence == "no_probe"
    assert "sonda" in explanation.lower()


def test_farm_probe_confidence_fresh_when_reading_recent():
    confidence, _ = _farm_probe_confidence(
        has_probe=True, last_reading_at=_NOW - timedelta(hours=2), now=_NOW
    )
    assert confidence == "fresh"


def test_farm_probe_confidence_stale_between_thresholds():
    confidence, _ = _farm_probe_confidence(
        has_probe=True, last_reading_at=_NOW - timedelta(hours=40), now=_NOW
    )
    assert confidence == "stale"


def test_farm_probe_confidence_forecast_only_when_dead_or_never_read():
    dead, _ = _farm_probe_confidence(
        has_probe=True, last_reading_at=_NOW - timedelta(hours=100), now=_NOW
    )
    never_read, _ = _farm_probe_confidence(has_probe=True, last_reading_at=None, now=_NOW)
    assert dead == "forecast_only"
    assert never_read == "forecast_only"


def _make_sector_ctx(**overrides) -> SectorAssistantContext:
    defaults = dict(
        sector_id="sec-001",
        sector_name="Norte",
        crop_type="olive",
        variety="Galega",
        phenological_stage="vegetative_growth",
        area_ha=5.0,
        config_status={"soil": "configured", "irrigation_system": "missing", "phenological_stage": "configured"},
        defaults_used=["Kc=0.65 (stage average)"],
        missing_config=["irrigation system not configured"],
        recommendation_id="rec-001",
        recommendation_action="irrigate",
        recommendation_is_accepted=None,
        irrigation_depth_mm=18.5,
        runtime_minutes=None,
        confidence_score=0.72,
        confidence_level="medium",
        reasons=[{"category": "water_balance", "message": "Depleção: 12mm de 18mm disponíveis"}],
        rootzone_depletion_mm=12.0,
        rootzone_taw_mm=90.0,
        rootzone_raw_mm=54.0,
        rootzone_swc=0.22,
        today_etc_mm=3.4,
        rainfall_effective_mm=0.0,
        rain_skip_applies=False,
        swc_source="probe_weighted",
        swc_model=None,
        fc_calibration=None,
        dose_band="normal",
        dose_source="configured",
        dose_presentation={"habitual_factor": 1.0},
        stress_projection={"urgency": "none"},
        confidence_penalties=[],
        today_et0_mm=4.1,
        today_temp_max_c=28.0,
        rainfall_last_24h_mm=0.0,
        forecast_rain_next_48h_mm=2.0,
        last_irrigation_date="2026-04-05",
        total_irrigation_7d_mm=25.0,
        active_alerts=[],
        probe_live=None,
        source_confidence="no_probe",
        data_quality_explanation="Sem sonda ativa — recomendação baseada em balanço hídrico.",
        generated_at="2026-04-08T08:00:00+00:00",
    )
    defaults.update(overrides)
    return SectorAssistantContext(**defaults)


def test_sector_context_is_json_serialisable():
    ctx = _make_sector_ctx()
    builder = AssistantContextBuilder()
    json_str = builder.to_json(ctx)
    parsed = json.loads(json_str)
    assert parsed["sector_name"] == "Norte"
    assert parsed["crop_type"] == "olive"


def test_sector_context_includes_config_status():
    ctx = _make_sector_ctx()
    assert "soil" in ctx.config_status
    assert "irrigation_system" in ctx.config_status


def test_sector_context_includes_defaults_used():
    ctx = _make_sector_ctx()
    assert isinstance(ctx.defaults_used, list)
    assert len(ctx.defaults_used) > 0


def test_sector_context_includes_missing_config():
    ctx = _make_sector_ctx()
    assert isinstance(ctx.missing_config, list)
    assert any("irrigation" in m for m in ctx.missing_config)


def test_farm_context_is_json_serialisable():
    sector = _make_sector_ctx()
    ctx = FarmAssistantContext(
        farm_id="farm-001",
        farm_name="Quinta do Norte",
        date="2026-04-08",
        location={"lat": 38.5, "lon": -8.1, "region": "Alentejo"},
        weather_summary={"et0_mm": 4.1, "rainfall_mm": 0.0, "temp_max_c": 28.0},
        sectors=[sector],
        total_active_alerts=0,
        missing_data_priorities=["irrigation system not configured"],
        setup_completion_pct=0.0,
    )
    builder = AssistantContextBuilder()
    json_str = builder.to_json(ctx)
    parsed = json.loads(json_str)
    assert parsed["farm_name"] == "Quinta do Norte"
    assert len(parsed["sectors"]) == 1
    assert "setup_completion_pct" in parsed


def test_farm_context_setup_completion_pct_type():
    sector = _make_sector_ctx(
        config_status={"soil": "configured", "irrigation_system": "configured"}
    )
    ctx = FarmAssistantContext(
        farm_id="farm-001",
        farm_name="Quinta",
        date="2026-04-08",
        location=None,
        weather_summary={},
        sectors=[sector],
        total_active_alerts=0,
        missing_data_priorities=[],
        setup_completion_pct=100.0,
    )
    assert isinstance(ctx.setup_completion_pct, float)
    assert ctx.setup_completion_pct == 100.0


def test_to_json_handles_none_values():
    ctx = _make_sector_ctx(
        variety=None,
        phenological_stage=None,
        recommendation_action=None,
        irrigation_depth_mm=None,
        confidence_score=None,
    )
    builder = AssistantContextBuilder()
    json_str = builder.to_json(ctx)
    parsed = json.loads(json_str)
    assert parsed["variety"] is None
    assert parsed["recommendation_action"] is None


def test_recommendation_snapshot_context_passes_through_engine_fields():
    snapshot = {
        "etc_mm": 3.4,
        "rain_effective_mm": 1.2,
        "rain_skip_applies": True,
        "swc_source": "probe_weighted",
        "swc_model": {"seed_kind": "rain_anchor"},
        "fc_calibration": {"method": "envelope"},
        "dose_band": "normal",
        "dose_source": "probe_learned",
        "dose_presentation": {"habitual_factor": 0.9},
        "stress_projection": {"urgency": "low"},
    }
    rec = SimpleNamespace(
        inputs_snapshot=snapshot,
        computation_log={"confidence_penalties": ["weather_stale"]},
    )

    context = _recommendation_snapshot_context(rec)

    assert context == {
        **snapshot,
        "confidence_penalties": ["weather_stale"],
    }
