"""Tests for IrrigationAssistant using MockChatClient and mocked context builder."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.assistant import IrrigationAssistant
from app.ai.context_builder import (
    AssistantContextBuilder,
    FarmAssistantContext,
    SectorAssistantContext,
)
from app.ai.openai_client import MockChatClient
from app.schemas.ai import AgronomicInterpretation

_MINIMAL_PROBE_STATS = {
    "probe_id": "probe-001",
    "probe_external_id": "EXT-001",
    "sector_id": "sec-001",
    "sector_name": "Norte",
    "soil_texture": None,
    "root_depth_cm": 60,
    "analysis_window_hours": 72,
    "n_irrigation_events_in_window": 1,
    "last_irrigation_applied_mm": 20.0,
    "depths": [
        {
            "depth_cm": 30,
            "n_readings": 24,
            "humidade_actual": "humidade adequada",
            "tendencia": "estável",
            "sinal_estavel": True,
            "causa_sinal_estavel": "humidade estável sem consumo nem recarga activos — equilíbrio hídrico",
            "profundidade_alem_raizes": False,
            "variabilidade_sinal": "muito baixa (sinal plano)",
            "variacao_24h": "sem variação significativa",
            "variacao_48h": "sem variação significativa",
            "resposta_rega": "moderada",
            "horas_ate_pico_apos_rega": 2.0,
        }
    ],
    "cross_depth_signals": {},
}

_NO_DEFICIT_PROBE_STATS = {
    **_MINIMAL_PROBE_STATS,
    "latest_recommendation": {
        "action": "no_irrigation",
        "generated_at": "2026-06-11T05:00:00+00:00",
        "depletion_mm": 0.0,
        "taw_mm": 90.0,
        "depletion_pct": 0.0,
        "irrigation_depth_mm": None,
    },
    "depths": [
        {
            **_MINIMAL_PROBE_STATS["depths"][0],
            "humidade_actual": "saturado / próximo da capacidade de campo",
        },
        {
            "depth_cm": 50,
            "n_readings": 24,
            "humidade_actual": "humidade crítica / próximo do ponto de murchamento",
            "tendencia": "estável",
            "sinal_estavel": True,
            "causa_sinal_estavel": "humidade estável sem consumo nem recarga activos — equilíbrio hídrico",
            "profundidade_alem_raizes": False,
            "variabilidade_sinal": "baixa",
            "variacao_24h": "sem variação significativa",
            "variacao_48h": "sem variação significativa",
            "resposta_rega": None,
            "horas_ate_pico_apos_rega": None,
        },
    ],
}


def _sector_ctx(**overrides) -> SectorAssistantContext:
    defaults = dict(
        sector_id="sec-001",
        sector_name="Norte",
        crop_type="olive",
        variety=None,
        phenological_stage="vegetative_growth",
        area_ha=5.0,
        config_status={"soil": "configured", "irrigation_system": "missing"},
        defaults_used=["Kc=0.65"],
        missing_config=["irrigation system not configured"],
        recommendation_action="irrigate",
        irrigation_depth_mm=18.5,
        runtime_minutes=None,
        confidence_score=0.72,
        confidence_level="medium",
        reasons=[{"category": "water_balance", "message": "Depleção: 12mm"}],
        rootzone_depletion_mm=12.0,
        rootzone_taw_mm=90.0,
        rootzone_raw_mm=54.0,
        rootzone_swc=0.22,
        today_et0_mm=4.1,
        today_temp_max_c=28.0,
        rainfall_last_24h_mm=0.0,
        forecast_rain_next_48h_mm=2.0,
        last_irrigation_date=None,
        total_irrigation_7d_mm=0.0,
        active_alerts=[],
        probe_live=None,
        source_confidence="high",
        data_quality_explanation="Good sensor data quality",
        generated_at="2026-04-08T08:00:00+00:00",
    )
    defaults.update(overrides)
    return SectorAssistantContext(**defaults)


def _farm_ctx() -> FarmAssistantContext:
    return FarmAssistantContext(
        farm_id="farm-001",
        farm_name="Quinta",
        date="2026-04-08",
        location={"lat": 38.5, "lon": -8.1, "region": "Alentejo"},
        weather_summary={"et0_mm": 4.1, "rainfall_mm": 0.0},
        sectors=[_sector_ctx()],
        total_active_alerts=0,
        missing_data_priorities=["irrigation system not configured"],
        setup_completion_pct=0.0,
    )


@pytest.fixture
def mock_builder():
    builder = MagicMock(spec=AssistantContextBuilder)
    builder.build_sector_context = AsyncMock(return_value=_sector_ctx())
    builder.build_farm_context = AsyncMock(return_value=_farm_ctx())
    builder.to_json = AssistantContextBuilder().to_json  # use real serialiser
    return builder


@pytest.fixture
def assistant(mock_builder):
    return IrrigationAssistant(
        context_builder=mock_builder,
        client=MockChatClient(),
        language="pt",
    )


@pytest.mark.asyncio
async def test_explain_recommendation_returns_nonempty(assistant):
    db = AsyncMock()
    result = await assistant.explain_recommendation("sec-001", db)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_explain_recommendation_no_rec_returns_message(mock_builder):
    mock_builder.build_sector_context = AsyncMock(
        return_value=_sector_ctx(recommendation_action=None)
    )
    asst = IrrigationAssistant(mock_builder, MockChatClient(), "pt")
    db = AsyncMock()
    result = await asst.explain_recommendation("sec-001", db)
    assert "recomendação" in result.lower()


@pytest.mark.asyncio
async def test_summarize_farm_returns_nonempty(assistant):
    db = AsyncMock()
    result = await assistant.summarize_farm("farm-001", db)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_generate_missing_data_questions_returns_list(assistant):
    db = AsyncMock()
    result = await assistant.generate_missing_data_questions("farm-001", db)
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(q, str) for q in result)


@pytest.mark.asyncio
async def test_chat_returns_nonempty(assistant):
    db = AsyncMock()
    result = await assistant.chat("farm-001", "Quando devo regar?", db)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_chat_with_sector_id_uses_sector_context(mock_builder, assistant):
    db = AsyncMock()
    await assistant.chat("farm-001", "Explica a recomendação", db, sector_id="sec-001")
    mock_builder.build_sector_context.assert_called_once_with("sec-001", db)
    mock_builder.build_farm_context.assert_not_called()


@pytest.mark.asyncio
async def test_chat_without_sector_id_uses_farm_context(mock_builder, assistant):
    db = AsyncMock()
    await assistant.chat("farm-001", "Resume a exploração", db, sector_id=None)
    mock_builder.build_farm_context.assert_called_once_with("farm-001", db)
    mock_builder.build_sector_context.assert_not_called()


@pytest.mark.asyncio
async def test_interpret_probe_structured_uses_advisory_prompt(assistant):
    """interpret_probe_patterns_structured must use PROBE_ADVISORY_PT, not PROBE_INTERPRETATION_PT."""
    captured: list[str] = []

    async def _capture(system_prompt, user_message, **kwargs):
        captured.append(system_prompt)
        # Return valid AgronomicInterpretation JSON so _parse_structured_output succeeds
        return json.dumps({
            "summary": "Sonda mostra humidade estável e adequada.",
            "risk_level": "low",
            "irrigation_advice": "Não há necessidade de regar nos próximos 1-2 dias. Monitoriza a tendência.",
            "evidence": [
                {"source": "depths[0].humidade_actual", "value": "humidade adequada"},
                {"source": "depths[0].tendencia", "value": "estável"},
            ],
            "missing_data": [],
            "confidence_score": 0.8,
            "confidence_explanation": "Sinal estável com leituras suficientes.",
            "recommended_actions": ["Monitorizar humidade nas próximas 24h"],
        })

    db = AsyncMock()
    with patch("app.ai.assistant.compute_probe_signal_stats", return_value=_MINIMAL_PROBE_STATS):
        assistant.client.complete = _capture
        result = await assistant.interpret_probe_patterns_structured("probe-001", db)

    assert len(captured) == 1
    # Advisory prompt is present
    assert "NÃO enumeres padrões por profundidade" in captured[0]
    # Old pattern enumeration heading is absent
    assert "PADRÕES A VERIFICAR" not in captured[0]
    # Returns a valid AgronomicInterpretation
    assert isinstance(result, AgronomicInterpretation)
    assert result.irrigation_advice != ""


@pytest.mark.asyncio
async def test_interpret_probe_structured_evidence_no_depth_pattern_labels(assistant):
    """Evidence items must not be per-depth 'Sinal Estável' pattern name labels."""
    db = AsyncMock()
    with patch("app.ai.assistant.compute_probe_signal_stats", return_value=_MINIMAL_PROBE_STATS):
        result = await assistant.interpret_probe_patterns_structured("probe-001", db)

    anti_pattern_values = {
        "Sinal Estável", "Equilíbrio hídrico", "Além das raízes",
        "Solo saturado", "Resposta fraca à rega", "Drenagem rápida",
    }
    for ev in result.evidence:
        # A source like "depths[0]" paired with a bare pattern-name value is the anti-pattern
        if ev.source.startswith("depths["):
            assert ev.value not in anti_pattern_values, (
                f"evidence has depth-pattern label: source={ev.source!r}, value={ev.value!r}"
            )


@pytest.mark.asyncio
async def test_interpret_probe_no_deficit_overrides_urgent_irrigation_advice(assistant):
    """Probe interpretation must not tell the user to irrigate when depletion is 0%."""

    async def _bad_model_output(system_prompt, user_message, **kwargs):
        return json.dumps({
            "summary": "A sonda indica humidade elevada nas camadas superiores, mas crítica a 50 cm.",
            "risk_level": "high",
            "irrigation_advice": "Rega urgente para evitar stress hídrico nas raízes.",
            "evidence": [
                {"source": "depths[1].humidade_actual", "value": "humidade crítica"},
                {"source": "depths[0].humidade_actual", "value": "humidade elevada"},
            ],
            "missing_data": [],
            "confidence_score": 0.7,
            "confidence_explanation": "Leituras recentes disponíveis.",
            "recommended_actions": ["Aplicar rega imediatamente."],
        })

    db = AsyncMock()
    with patch("app.ai.assistant.compute_probe_signal_stats", return_value=_NO_DEFICIT_PROBE_STATS):
        assistant.client.complete = _bad_model_output
        result = await assistant.interpret_probe_patterns_structured("probe-001", db)

    assert result.risk_level == "low"
    assert "Não regues agora" in result.irrigation_advice
    assert all("urgente" not in action.lower() for action in result.recommended_actions)
    assert any(ev.source == "latest_recommendation.depletion_pct" for ev in result.evidence)


def test_render_probe_interpretation_includes_summary_advice_evidence_and_action(assistant):
    """Probe card renderer must keep the summary/advisory format expected by the UI."""
    interpretation = AgronomicInterpretation(
        summary="Sonda mostra humidade estável e adequada.",
        risk_level="low",
        irrigation_advice="Não há necessidade de regar agora.",
        evidence=[
            {"source": "depths[0].humidade_actual", "value": "humidade adequada"},
            {"source": "depths[0].tendencia", "value": "estável"},
        ],
        missing_data=[],
        confidence_score=0.82,
        confidence_explanation="Leituras suficientes e coerentes.",
        recommended_actions=["Monitorizar a tendência nas próximas 24h."],
    )

    rendered = assistant.render_probe_interpretation(interpretation)

    assert rendered.splitlines()[0] == "• Resumo: Sonda mostra humidade estável e adequada."
    assert "• Conselho: Não há necessidade de regar agora." in rendered
    assert "• Evidência: humidade adequada; estável" in rendered
    assert "• Próxima ação: Monitorizar a tendência nas próximas 24h." in rendered
