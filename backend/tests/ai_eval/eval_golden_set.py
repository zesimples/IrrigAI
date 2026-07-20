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
from app.ai.openai_client import OpenAIChatClient
from app.config import Settings
from app.schemas.ai import AgronomicInterpretation
from tests.ai_eval.harness import (
    assert_evidence_ids_match_registry,
    assert_evidence_sources_resolve,
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
    return cases


CASES = _load_cases()


@pytest.fixture(scope="module")
def live_client() -> OpenAIChatClient:
    settings = Settings()
    if settings.LLM_PROVIDER != "openai":
        pytest.skip("live AI eval requires LLM_PROVIDER=openai")
    if not settings.OPENAI_API_KEY:
        pytest.skip("live AI eval skipped: OPENAI_API_KEY is not configured")
    return OpenAIChatClient(settings.OPENAI_API_KEY, settings.OPENAI_MODEL)


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
    else:  # pragma: no cover - fixture schema guard
        raise AssertionError(f"unknown eval surface: {surface}")
    return system, case["user_message"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.asyncio
async def test_live_golden_context(case: dict, live_client: OpenAIChatClient) -> None:
    system_prompt, user_message = _prompt_for(case)
    assistant = IrrigationAssistant(AssistantContextBuilder(), live_client, "pt")
    evidence_context = (
        {"probe_signal": case["context"]}
        if case["surface"] == "probe"
        else case["context"]
    )
    result = await assistant._complete_structured(
        system_prompt=system_prompt,
        user_message=user_message,
        context=evidence_context,
        max_tokens=900,
    )
    assert isinstance(result, AgronomicInterpretation)

    if case["surface"] == "probe":
        result = assistant._apply_probe_recommendation_guard(case["context"], result)

    assert_response_is_pt_pt(result)
    assert_evidence_sources_resolve(result, evidence_context)
    assert_evidence_ids_match_registry(result, evidence_context)

    if case["surface"] == "probe":
        assert_probe_guard_holds(result, case["context"])
        assert_no_raw_vwc_decimals(result)
    elif case["surface"] == "farm":
        assert_farm_urgent_actions_match_engine(result, case["context"])
