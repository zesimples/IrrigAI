"""Tests for IrrigationAssistant using MockChatClient and mocked context builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.assistant import IrrigationAssistant
from app.ai.context_builder import (
    AssistantContextBuilder,
    FarmAssistantContext,
    SectorAssistantContext,
)
from app.ai.context_v2 import SECTOR_AI_CONTEXT_BLOCKS, SectorAIContextV2
from app.ai.openai_client import MockChatClient
from app.schemas.ai import AgronomicInterpretation, AgronomicInterpretationDraft

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
    # Mirrors production: engine action is "skip" (the real "Não regar" value —
    # the enum has no "no_irrigation") and depletion is well above the 5% floor,
    # so only the action check can suppress urgent-irrigation advice.
    "latest_recommendation": {
        "action": "skip",
        "generated_at": "2026-06-16T05:00:00+00:00",
        "depletion_mm": 49.4,
        "taw_mm": 104.0,
        "depletion_pct": 47.5,
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
        recommendation_id="rec-001",
        recommendation_action="irrigate",
        recommendation_is_accepted=None,
        irrigation_depth_mm=18.5,
        runtime_minutes=None,
        confidence_score=0.72,
        confidence_level="medium",
        reasons=[{"category": "water_balance", "message": "Depleção: 12mm"}],
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


def _sector_v2(action: str | None = "irrigate") -> SectorAIContextV2:
    blocks = {
        name: {"observed_at": None, "source": "test", "units": {}}
        for name in SECTOR_AI_CONTEXT_BLOCKS
    }
    blocks["scope"].update(
        detail_level="compact",
        sector={"id": "sec-001", "name": "Norte"},
    )
    blocks["engine_decision"].update(
        action=action,
        confidence_level="medium",
    )
    blocks["water_balance"].update(depletion_mm=12.0)
    blocks["probe_state"].update(data_quality={"fresh_depths": 0, "total_depths": 0})
    blocks["alerts_and_limitations"].update(known_limitations=[])
    return SectorAIContextV2(**blocks)


@pytest.fixture
def mock_builder():
    builder = MagicMock(spec=AssistantContextBuilder)
    builder.build_sector_context = AsyncMock(return_value=_sector_ctx())
    builder.build_sector_ai_context = AsyncMock(return_value=_sector_v2())
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
    assistant.context_builder.build_sector_ai_context.assert_called_once_with(
        "sec-001", db, compact=True
    )


@pytest.mark.asyncio
async def test_explain_recommendation_no_rec_returns_message(mock_builder):
    mock_builder.build_sector_ai_context = AsyncMock(return_value=_sector_v2(action=None))
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
    mock_builder.build_sector_ai_context.assert_called_once_with(
        "sec-001", db, compact=False
    )
    mock_builder.build_farm_context.assert_not_called()


@pytest.mark.asyncio
async def test_chat_without_sector_id_uses_farm_context(mock_builder, assistant):
    db = AsyncMock()
    await assistant.chat("farm-001", "Resume a exploração", db, sector_id=None)
    mock_builder.build_farm_context.assert_called_once_with("farm-001", db)
    mock_builder.build_sector_ai_context.assert_not_called()


@pytest.mark.asyncio
async def test_sector_diagnosis_uses_full_v2_context(mock_builder, assistant):
    db = AsyncMock()

    await assistant.diagnose_sector("sec-001", db)

    mock_builder.build_sector_ai_context.assert_called_once_with(
        "sec-001", db, compact=False
    )


@pytest.mark.asyncio
async def test_interpret_probe_structured_uses_advisory_prompt(assistant):
    """interpret_probe_patterns_structured must use PROBE_ADVISORY_PT, not PROBE_INTERPRETATION_PT."""
    captured: list[str] = []

    async def _capture(system_prompt, user_message, schema_model, **kwargs):
        captured.append(system_prompt)
        # Return a valid AgronomicInterpretation directly (native structured path)
        return AgronomicInterpretation(
            summary="Sonda mostra humidade estável e adequada.",
            risk_level="low",
            irrigation_advice="Não há necessidade de regar nos próximos 1-2 dias. Monitoriza a tendência.",
            evidence=[
                {"source": "depths[0].humidade_actual", "value": "humidade adequada"},
                {"source": "depths[0].tendencia", "value": "estável"},
            ],
            missing_data=[],
            confidence_score=0.8,
            confidence_explanation="Sinal estável com leituras suficientes.",
            recommended_actions=["Monitorizar humidade nas próximas 24h"],
        )

    db = AsyncMock()
    with patch("app.ai.assistant.compute_probe_signal_stats", return_value=_MINIMAL_PROBE_STATS):
        assistant.client.complete_structured = _capture
        result = await assistant.interpret_probe_patterns_structured("probe-001", db)

    assert len(captured) == 1
    # Advisory prompt is present and probe-focused.
    assert "leitura agronómica da sonda" in captured[0]
    assert "perfil de humidade por profundidade" in captured[0]
    # Old pattern enumeration heading is absent
    assert "PADRÕES A VERIFICAR" not in captured[0]
    assert "flatline" in captured[0]
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
    """When the engine says skip/defer, the guard neutralises the irrigation advice
    but PRESERVES the LLM's depth description (summary + depth evidence)."""

    depth_summary = "Humidade elevada à superfície mas crítica a 50 cm, com consumo nas camadas fundas."

    async def _bad_model_output(system_prompt, user_message, schema_model, **kwargs):
        return AgronomicInterpretation(
            summary=depth_summary,
            risk_level="high",
            irrigation_advice="Rega urgente para evitar stress hídrico nas raízes.",
            evidence=[
                {"source": "depths[1].humidade_actual", "value": "humidade crítica a 50 cm"},
                {"source": "depths[0].humidade_actual", "value": "humidade elevada a 5 cm"},
            ],
            missing_data=[],
            confidence_score=0.7,
            confidence_explanation="Leituras recentes disponíveis.",
            recommended_actions=["Aplicar rega imediatamente."],
        )

    db = AsyncMock()
    with patch("app.ai.assistant.compute_probe_signal_stats", return_value=_NO_DEFICIT_PROBE_STATS):
        assistant.client.complete_structured = _bad_model_output
        result = await assistant.interpret_probe_patterns_structured("probe-001", db)

    # Advice/risk/actions neutralised to align with the engine decision.
    assert result.risk_level == "low"
    assert "Não regues agora" in result.irrigation_advice
    assert all("urgente" not in action.lower() for action in result.recommended_actions)
    # The engine decision is surfaced as evidence...
    assert any(
        ev.source == "probe_signal.latest_recommendation.action"
        for ev in result.evidence
    )
    # ...and the LLM's depth description is preserved (not replaced by generic text).
    assert result.summary == depth_summary
    assert any(
        ev.source == "probe_signal.depths[1].humidade_actual"
        and "humidade crítica" in ev.value
        for ev in result.evidence
    )


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

    assert rendered.splitlines()[0] == "• Perfil da sonda: Sonda mostra humidade estável e adequada."
    assert "• Conselho: Não há necessidade de regar agora." in rendered
    assert "• Sinais observados: humidade adequada; estável" in rendered
    assert "• Próxima verificação: Monitorizar a tendência nas próximas 24h." in rendered


@pytest.mark.asyncio
async def test_complete_structured_uses_native_parse(monkeypatch):
    """The structured path must call client.complete_structured, not parse JSON text."""
    from app.schemas.ai import AgronomicInterpretation

    client = MockChatClient()
    called = {}

    async def spy_complete_structured(system, user, schema, **kw):
        called["hit"] = True
        return AgronomicInterpretation(
            summary="ok", risk_level="low", irrigation_advice="monitorizar",
            evidence=[], missing_data=[], confidence_score=0.8,
            confidence_explanation="teste", recommended_actions=[],
        )

    monkeypatch.setattr(client, "complete_structured", spy_complete_structured)
    assistant = IrrigationAssistant(
        context_builder=AssistantContextBuilder(), client=client, language="pt"
    )
    result = await assistant._complete_structured(
        system_prompt="x", user_message="y", context={"known_limitations": []},
    )
    assert called.get("hit") is True
    assert result.summary == "ok"


@pytest.mark.asyncio
async def test_complete_structured_rejects_unknown_evidence_id(monkeypatch):
    client = MockChatClient()

    async def invalid_citation(system, user, schema, **kw):
        assert schema is AgronomicInterpretationDraft
        return AgronomicInterpretationDraft(
            summary="O solo mantém reserva suficiente.",
            risk_level="low",
            irrigation_advice="Não regar agora.",
            evidence=[{"evidence_id": "ev_invented"}],
            missing_data=[],
            confidence_score=0.8,
            confidence_explanation="Dados actuais e coerentes.",
            recommended_actions=["Monitorizar amanhã."],
        )

    monkeypatch.setattr(client, "complete_structured", invalid_citation)
    assistant = IrrigationAssistant(AssistantContextBuilder(), client, "pt")

    result = await assistant._complete_structured(
        system_prompt="x",
        user_message="y",
        context={"water_balance": {"depletion_mm": 12.5}},
    )

    assert result.evidence
    assert all(evidence.evidence_id != "ev_invented" for evidence in result.evidence)
    assert result.evidence[0].source == "water_balance.depletion_mm"
    assert result.evidence[0].value == "12,5"


@pytest.mark.asyncio
async def test_complete_structured_injects_pt_output_contract(monkeypatch):
    """The native structured path must tell the model to fill ALL fields in
    European Portuguese and to cite canonical context source paths.

    This guidance lived in STRUCTURED_OUTPUT_PT, which the native-json_schema
    migration (376467d) deleted without folding it into the card templates.
    Without it the model returns English evidence values and invents source
    keys (e.g. "sectors.recommendation_action") that render_structured cannot
    map to a Portuguese _SRC_LABEL, producing raw bullets like
    "Sectors Recommendation Action: irrigate"."""
    client = MockChatClient()
    captured: dict[str, str] = {}

    async def spy(system, user, schema, **kw):
        captured["system"] = system
        return AgronomicInterpretation(
            summary="ok", risk_level="low", irrigation_advice="monitorizar",
            evidence=[], missing_data=[], confidence_score=0.8,
            confidence_explanation="teste", recommended_actions=[],
        )

    monkeypatch.setattr(client, "complete_structured", spy)
    assistant = IrrigationAssistant(
        context_builder=AssistantContextBuilder(), client=client, language="pt"
    )
    await assistant._complete_structured(
        system_prompt="RESUMO DA EXPLORAÇÃO base prompt.",
        user_message="y",
        context={"known_limitations": []},
    )

    system = captured["system"]
    # Base prompt is preserved.
    assert "RESUMO DA EXPLORAÇÃO base prompt." in system
    # All structured fields must be in Portuguese (translate English context values).
    assert "português" in system.lower()
    # The model may cite only backend-issued IDs, never free-form paths/values.
    assert "evidence_id" in system
    assert "REGISTO DE EVIDÊNCIA PERMITIDA" in system


@pytest.mark.asyncio
async def test_complete_structured_fallback_low_confidence_on_error(monkeypatch):
    client = MockChatClient()

    async def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(client, "complete_structured", boom)
    assistant = IrrigationAssistant(
        context_builder=AssistantContextBuilder(), client=client, language="pt"
    )
    result = await assistant._complete_structured(
        system_prompt="x", user_message="y", context={"known_limitations": ["sem sondas"]},
    )
    assert result.confidence_score <= 0.3


@pytest.mark.parametrize("language", ["pt", "en"])
def test_farm_summary_prompt_gates_on_real_recommendation_actions(language):
    """The farm-summary prompt must key 'no irrigation needed' off the real engine
    values (skip/defer), never the phantom 'no_irrigation' that the enum never emits.

    context_builder passes rec.action verbatim, so a prompt that tells the LLM to
    match 'no_irrigation' matches nothing — the same phantom-value class of bug that
    broke the sector probe-guard (commit 1fad961)."""
    from app.ai.prompt_templates import get_farm_summary_template
    from app.core.enums import RecommendationAction

    template = get_farm_summary_template(language)

    assert "no_irrigation" not in template
    # The real "Não regar" decisions must be named so the LLM can group them.
    assert RecommendationAction.SKIP.value in template
    assert RecommendationAction.DEFER.value in template
