import pytest

from app.ai.evidence import build_evidence_registry
from app.schemas.ai import AgronomicInterpretation
from tests.ai_eval.harness import (
    assert_evidence_ids_match_registry,
    assert_evidence_sources_resolve,
    assert_farm_urgent_actions_match_engine,
    assert_no_raw_vwc_decimals,
    assert_probe_guard_holds,
    assert_response_is_pt_pt,
)


def _interpretation(**overrides) -> AgronomicInterpretation:
    values = {
        "summary": "O setor mantém água suficiente.",
        "risk_level": "low",
        "irrigation_advice": "Não regar agora; monitorizar a sonda.",
        "evidence": [{"source": "water_balance.depletion_mm", "value": "12 mm"}],
        "missing_data": [],
        "confidence_score": 0.8,
        "confidence_explanation": "Leituras atuais e coerentes.",
        "recommended_actions": ["Confirmar novamente amanhã."],
    }
    values.update(overrides)
    return AgronomicInterpretation.model_validate(values)


def test_eval_evidence_path_validation_supports_nested_lists():
    context = {"water_balance": {"depletion_mm": 12}, "depths": [{"status": "ok"}]}
    interpretation = _interpretation(
        evidence=[
            {"source": "water_balance.depletion_mm", "value": "12 mm"},
            {"source": "depths[0].status", "value": "ok"},
        ]
    )

    assert_evidence_sources_resolve(interpretation, context)


def test_eval_evidence_ids_and_values_match_backend_registry():
    context = {"water_balance": {"depletion_mm": 12.5}}
    registry = build_evidence_registry(context)
    entry = registry.entry_for_path("water_balance.depletion_mm")
    assert entry is not None
    interpretation = _interpretation(evidence=[entry.to_evidence().model_dump()])

    assert_evidence_ids_match_registry(interpretation, context)


def test_eval_evidence_path_validation_rejects_missing_paths():
    interpretation = _interpretation(
        evidence=[{"source": "water_balance.missing", "value": "12 mm"}]
    )

    with pytest.raises(AssertionError, match="does not resolve"):
        assert_evidence_sources_resolve(
            interpretation,
            {"water_balance": {"depletion_mm": 12}},
        )


def test_eval_language_check_rejects_obvious_english_fields():
    valid = _interpretation()
    assert_response_is_pt_pt(valid)

    invalid = _interpretation(confidence_explanation="Current data should be monitored.")
    with pytest.raises(AssertionError, match="English"):
        assert_response_is_pt_pt(invalid)


def test_eval_probe_output_rejects_raw_vwc_decimals():
    interpretation = _interpretation(summary="Humidade atual 0,341 m³/m³.")

    try:
        assert_no_raw_vwc_decimals(interpretation)
    except AssertionError:
        pass
    else:
        raise AssertionError("raw VWC decimal was accepted")


def test_eval_probe_guard_requires_no_irrigation_advice_for_skip():
    context = {"latest_recommendation": {"action": "skip"}}
    assert_probe_guard_holds(_interpretation(), context)

    invalid = _interpretation(
        risk_level="high",
        irrigation_advice="Regar urgentemente.",
        recommended_actions=["Iniciar rega urgente."],
    )
    with pytest.raises(AssertionError):
        assert_probe_guard_holds(invalid, context)


def test_eval_farm_urgent_action_cannot_name_skip_sector():
    context = {
        "sectors": [
            {"sector_name": "Norte", "recommendation_action": "irrigate"},
            {"sector_name": "Sul", "recommendation_action": "skip"},
        ]
    }
    valid = _interpretation(irrigation_advice="Rega urgente: Norte.")
    assert_farm_urgent_actions_match_engine(valid, context)

    invalid = _interpretation(irrigation_advice="Rega urgente: Sul.")
    try:
        assert_farm_urgent_actions_match_engine(invalid, context)
    except AssertionError:
        pass
    else:
        raise AssertionError("skip sector was accepted as urgent")
