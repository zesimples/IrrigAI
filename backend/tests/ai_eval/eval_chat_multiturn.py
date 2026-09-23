"""Opt-in live evaluation of multi-turn chat and the proposed-action lifecycle.

Like ``eval_golden_set.py``, this filename deliberately does not start with
``test_`` so normal pytest and CI discovery never calls a paid external service.

Tool execution is stubbed with fixture results so the *model* is the only variable:
the DB, the engine, and access control are already covered by deterministic tests.
What is evaluated here is what only a live model can show — whether a real answer
stays inside the data it was given across several turns, and whether a proposal
stays a proposal.

Outcomes are recorded in three separate buckets, because collapsing them hides the
one that matters:

* ``model``   — the model produced an answer the deterministic checks rejected.
* ``provider``— the API call itself failed (timeout, 5xx, refusal).
* ``skipped`` — no credentials; nothing was evaluated and nothing is proven.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.ai.chat_agent import ChatAgent
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import OpenAIChatClient, get_chat_client
from app.config import Settings
from tests.ai_eval.harness import (
    assert_action_lifecycle_is_terminal,
    assert_chat_reply_is_grounded,
    assert_notes_are_data_not_instructions,
    assert_weather_scope_is_explicit,
)

_CASES_PATH = Path(__file__).with_name("cases") / "chat_multiturn.json"


def _load_cases() -> list[dict]:
    return json.loads(_CASES_PATH.read_text(encoding="utf-8"))["cases"]


CASES = _load_cases()


def _advises_irrigation(reply: str) -> bool:
    """Use the product's own negation-aware predicate, not a substring scan."""
    from app.ai.chat_grounding import _IRRIGATE_DIRECTIVE_RE, _advises

    return _advises(reply, _IRRIGATE_DIRECTIVE_RE)


@dataclass
class RunLedger:
    """Model quality, provider health, and skips are three different questions."""

    model_failures: list[str] = field(default_factory=list)
    provider_failures: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)

    def report(self) -> str:
        return (
            f"passed={len(self.passed)} "
            f"model_failures={len(self.model_failures)} "
            f"provider_failures={len(self.provider_failures)}\n"
            + "\n".join(f"  model:    {item}" for item in self.model_failures)
            + ("\n" if self.model_failures else "")
            + "\n".join(f"  provider: {item}" for item in self.provider_failures)
        )


LEDGER = RunLedger()


@pytest.fixture(scope="module")
def live_client() -> OpenAIChatClient:
    settings = Settings()
    if settings.LLM_PROVIDER != "openai":
        pytest.skip("live chat eval requires LLM_PROVIDER=openai")
    if not settings.OPENAI_API_KEY:
        pytest.skip("live chat eval skipped: OPENAI_API_KEY is not configured")
    client = get_chat_client(settings)
    assert isinstance(client, OpenAIChatClient)
    return client


@pytest.fixture(scope="module", autouse=True)
def _print_ledger():
    yield
    print("\nchat eval ledger: " + LEDGER.report())


class _StubAccess:
    """Ownership is exercised by the deterministic API tests, not by a paid run."""

    async def farm(self, *_args, **_kwargs):
        return object()

    async def sector(self, *_args, **_kwargs):
        return object()

    async def sector_in_farm(self, *_args, **_kwargs):
        return object()

    async def recommendation(self, *_args, **_kwargs):
        return object()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.asyncio
async def test_live_multiturn_chat(
    case: dict, live_client: OpenAIChatClient, monkeypatch, record_property
) -> None:
    tool_results: dict = case["tool_results"]
    observed: list[dict] = []
    drafts: list[str] = []
    original_loop = live_client.run_tool_loop

    async def capture_draft(*args, **kwargs):
        response = await original_loop(*args, **kwargs)
        if response.content:
            drafts.append(response.content)
        return response

    monkeypatch.setattr(live_client, "run_tool_loop", capture_draft)

    async def _stub_execute_tool(name, args, *, access, db, scope, session=None):
        result = tool_results.get(name)
        if result is None:
            if name.startswith("propose_"):
                result = {
                    "proposed_action": {
                        "type": name.removeprefix("propose_"),
                        "summary": "Proposta para confirmação do utilizador.",
                        "sector_id": scope.sector_id,
                        "recommendation_id": args.get("recommendation_id"),
                        "params": {},
                    },
                    "status": "awaiting_confirmation",
                }
            else:
                result = {"error": "not_available_in_eval"}
        observed.append({"tool": name, "result": result})
        return result

    monkeypatch.setattr("app.ai.chat_agent.execute_tool", _stub_execute_tool)

    agent = ChatAgent(client=live_client, context_builder=AssistantContextBuilder(), language="pt")
    history: list = []
    proposals: list[str] = []
    # The API accumulates verified evidence across a conversation; the eval must do
    # the same or it measures a handicapped version of the product.
    prior_evidence: list[dict] = []
    # validated / repaired / fallback per turn: a repair that then passes is invisible
    # in the pass count, so it is recorded (see tests/ai_eval/conftest.py).
    turn_statuses: list[str] = []
    turn_issues: list[list[str]] = []
    record_property("turn_statuses", turn_statuses)
    record_property("turn_issues", turn_issues)
    turn_replies: list[dict] = []  # the exact replies judged, for the human review pack
    record_property("turn_replies", turn_replies)
    # Every model draft, including those a repair replaced: judging whether a repair
    # was a true or false positive needs the text it rejected.
    record_property("drafts", drafts)

    for turn in case["turns"]:
        observed.clear()  # Only this turn's reads may support current claims.
        try:
            result = await agent.run(
                farm_id=case["farm_id"],
                sector_id=case["sector_id"],
                message=turn,
                history=history,
                access=_StubAccess(),  # type: ignore[arg-type]
                db=None,  # type: ignore[arg-type]
                prior_evidence=list(prior_evidence),
            )
        except Exception as exc:  # provider-side failure, not model quality
            LEDGER.provider_failures.append(f"{case['id']}: {type(exc).__name__}: {exc}")
            pytest.fail(f"provider failure (not a model-quality result): {exc}")

        turn_statuses.append(result.validation_status)
        turn_issues.append(list(result.validation_issues))
        turn_replies.append(
            {
                "user": turn,
                "reply": result.reply,
                "proposed_action": result.proposed_action.model_dump(mode="json")
                if result.proposed_action
                else None,
            }
        )
        try:
            _check_turn(case, result, observed, prior_evidence, turn)
        except AssertionError as exc:
            LEDGER.model_failures.append(f"{case['id']} @ {turn!r}: {exc}")
            raise AssertionError(f"{exc}\nSynthetic-fixture model drafts: {drafts[-3:]}") from exc

        if result.proposed_action is not None:
            proposals.append("pending")
        prior_evidence.extend(item.model_dump() for item in result.evidence)

        from app.schemas.ai import ChatTurn

        history.append(ChatTurn(role="user", content=turn))
        history.append(ChatTurn(role="assistant", content=result.reply))

    if case.get("expect_proposal"):
        assert proposals, "the model never proposed the action the user asked for"
        # A proposal must stay a proposal until the user confirms it.
        assert_action_lifecycle_is_terminal(proposals)

    LEDGER.passed.append(case["id"])


def _check_turn(
    case: dict,
    result,
    observed: list[dict],
    prior_evidence: list[dict],
    user_message: str,
) -> None:
    reply = result.reply
    assert reply.strip(), "empty chat reply"

    # A fallback is a real outcome, but it means the model failed the grounding
    # check — record it as such rather than passing on the deterministic rescue.
    assert result.validation_status != "fallback", (
        "reply failed grounding and fell back to deterministic output: "
        + "; ".join(result.validation_issues)
    )
    assert_chat_reply_is_grounded(
        reply,
        observed,
        prior_evidence=prior_evidence,
        user_message=user_message,
    )

    if case.get("expect_no_irrigation_directive"):
        assert not _advises_irrigation(reply), (
            "reply advises irrigation against a non-irrigate engine decision: " + reply
        )

    if case.get("injected_note"):
        assert_notes_are_data_not_instructions(reply, case["injected_note"])

    weather = next(
        (entry["result"] for entry in observed if entry["tool"] == "get_weather"),
        None,
    )
    if weather is not None:
        assert_weather_scope_is_explicit(weather)
