"""Opt-in live-model evaluations for IrrigAI's grounded AI surfaces.

This filename deliberately does not start with ``test_``.  Run it explicitly as
documented in ``tests/ai_eval/README.md``; normal pytest/CI discovery skips it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai import prompt_templates
from app.ai.assistant import IrrigationAssistant
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import OpenAIChatClient, get_chat_client
from app.config import Settings
from app.schemas.ai import AgronomicInterpretation
from tests.ai_eval.harness import (
    assert_confidence_is_server_derived,
    assert_engine_reason_is_preserved,
    assert_evidence_ids_match_registry,
    assert_evidence_sources_resolve,
    assert_farm_no_need_claims_match_engine,
    assert_farm_urgent_actions_match_engine,
    assert_no_raw_vwc_decimals,
    assert_probe_guard_holds,
    assert_response_is_pt_pt,
)

_CASES_PATH = Path(__file__).with_name("cases") / "golden_contexts.json"


def _load_cases() -> list[dict]:
    payload = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert 18 <= len(cases) <= 22, "golden set should stay close to 20 cases"
    cases.extend(
        json.loads(_CASES_PATH.with_name("additional_surfaces.json").read_text(encoding="utf-8"))[
            "cases"
        ]
    )
    return cases


CASES = _load_cases()


@pytest.fixture(scope="module")
def live_client() -> OpenAIChatClient:
    settings = Settings()
    if settings.LLM_PROVIDER != "openai":
        pytest.skip("live AI eval requires LLM_PROVIDER=openai")
    if not settings.OPENAI_API_KEY:
        pytest.skip("live AI eval skipped: OPENAI_API_KEY is not configured")
    client = get_chat_client(settings)
    assert isinstance(client, OpenAIChatClient)
    return client


def _prompt_for(case: dict) -> tuple[str, str]:
    context = case["context"]
    context_json = json.dumps(context, ensure_ascii=False, default=str, indent=2)
    surface = case["surface"]
    if surface == "recommendation":
        system = prompt_templates.RECOMMENDATION_EXPLANATION_PT.format(
            context_json=context_json,
            user_notes=case.get("user_notes", "Nenhuma observação adicional."),
        )
    elif surface == "probe":
        system = prompt_templates.PROBE_ADVISORY_PT.format(signal_json=context_json)
    elif surface == "farm":
        system = prompt_templates.FARM_SUMMARY_PT.format(context_json=context_json)
    elif surface in {"alert_explanation", "change_analysis", "irrigation_effectiveness"}:
        template = {
            "alert_explanation": prompt_templates.ANOMALY_EXPLANATION_PT,
            "change_analysis": prompt_templates.SECTOR_CHANGE_ANALYSIS_PT,
            "irrigation_effectiveness": prompt_templates.IRRIGATION_EFFECTIVENESS_PT,
        }[surface]
        system = template.format(context_json=context_json)
    else:  # pragma: no cover - fixture schema guard
        raise AssertionError(f"unknown eval surface: {surface}")
    return system, case["user_message"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.asyncio
async def test_live_golden_context(
    case: dict, live_client: OpenAIChatClient, record_property
) -> None:
    system_prompt, user_message = _prompt_for(case)
    assistant = IrrigationAssistant(AssistantContextBuilder(), live_client, "pt")
    evidence_context = (
        {"probe_signal": case["context"]} if case["surface"] == "probe" else case["context"]
    )
    result = await assistant._complete_structured(
        system_prompt=system_prompt,
        user_message=user_message,
        context=evidence_context,
        max_tokens=900,
        surface={
            "recommendation": "recommendation",
            "probe": "probe_diagnosis",
            "farm": "farm_summary",
            "alert_explanation": "alert_explanation",
            "change_analysis": "change_analysis",
            "irrigation_effectiveness": "irrigation_effectiveness",
        }[case["surface"]],
    )
    assert isinstance(result, AgronomicInterpretation)
    assert not result.degraded, "A degraded fallback is not a successful live-model evaluation"

    if case["surface"] == "probe":
        # Mirror interpret_probe_patterns_structured(): the evidence registry cites
        # paths under the "probe_signal" wrapper, but confidence is derived from the
        # unwrapped stats. Skipping this step would evaluate a shape production
        # never returns.
        result = assistant._apply_deterministic_confidence(
            result,
            case["context"],
            explanation_status="degraded" if result.degraded else "generated",
        )
        result = assistant._apply_probe_recommendation_guard(case["context"], result)
    elif case["surface"] == "farm":
        # Mirror summarize_farm_structured(): irrigation advice is written from the
        # engine's per-sector decisions, not trusted from the model.
        result = assistant._apply_farm_recommendation_guard(case["context"], result)

    record_property("degraded", bool(getattr(result, "degraded", False)))
    # The exact response judged here, for the human review pack.
    record_property("output", result.model_dump(mode="json"))
    assert_response_is_pt_pt(result)
    assert_evidence_sources_resolve(result, evidence_context)
    assert_evidence_ids_match_registry(result, evidence_context)
    # A1: confidence is a deterministic function of the engine and the data, never
    # of how confident the sentence sounds. Probe surfaces wrap the context under
    # "probe_signal" for the evidence registry only — confidence is derived from the
    # unwrapped stats, exactly as `_apply_probe_recommendation_guard` does.
    assert_confidence_is_server_derived(
        result,
        case["context"] if case["surface"] == "probe" else evidence_context,
    )

    if case["surface"] == "probe":
        assert_probe_guard_holds(result, case["context"])
        assert_engine_reason_is_preserved(result, case["context"])
        assert_no_raw_vwc_decimals(result)
    elif case["surface"] == "farm":
        assert_farm_urgent_actions_match_engine(result, case["context"])
        assert_farm_no_need_claims_match_engine(result, case["context"])
