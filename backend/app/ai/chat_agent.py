"""Agentic chat loop: history + tools, grounded prose output, propose-only writes.

The loop is an **event producer**. The old implementation ran the whole turn and
then sliced the finished string into 80-character chunks, so the first byte a user
saw arrived after the last token was generated — chunking, not streaming. Progress
events are emitted as the work happens; answer content is emitted only after the
deterministic grounding checks in ``chat_grounding`` have passed, so responsiveness
never costs the reader an unchecked agronomic claim.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.access import AccessController
from app.ai import prompt_templates
from app.ai.chat_grounding import (
    TOOL_MEASUREMENT_UNITS,
    GroundedFacts,
    collect_data_timestamps,
    collect_facts,
    deterministic_fallback_reply,
    select_chat_evidence,
    validate_reply,
)
from app.ai.context_builder import AssistantContextBuilder
from app.ai.evidence import build_evidence_registry
from app.ai.openai_client import MockChatClient, OpenAIChatClient
from app.ai.tools import TOOL_SPECS, ToolScope, ToolSession, execute_tool
from app.schemas.ai import AgronomicEvidence, ChatTurn, ProposedAction
from app.services.ai_runtime import CONTRACT_VERSION, context_digest

MAX_HISTORY_TURNS = 8
MAX_ITERATIONS = 4
# One repair attempt. A second would mostly buy latency: a model that ignored an
# explicit list of unsupported values once rarely fixes it on the third try, and
# the deterministic fallback is always available.
MAX_REPAIRS = 1

_TOOL_PROGRESS_PT = {
    "get_farm_overview": "A consultar os setores da exploração…",
    "get_sector_status": "A ler o estado hídrico do setor…",
    "get_probe_readings": "A ler as sondas…",
    "get_water_events": "A rever as entradas de água detectadas…",
    "get_weather": "A consultar a meteorologia do âmbito…",
    "get_field_observations": "A recuperar as notas de campo…",
    "get_outcomes": "A rever os resultados das regas…",
    "get_calibration_status": "A verificar a calibração do solo…",
    "get_recommendation_history": "A rever o histórico de recomendações…",
    "get_flowmeter_summary": "A rever a execução das regas…",
    "get_stress_projection": "A projectar o stress hídrico…",
}
_DEFAULT_PROGRESS_PT = "A consultar dados…"

_BLOCK_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ý“\"'])|\n+")


@dataclass
class ChatEvent:
    """One step the caller may surface immediately."""

    type: str  # progress | answer | done
    payload: dict


@dataclass
class ChatResult:
    reply: str
    proposed_action: ProposedAction | None = None
    degraded: bool = False
    model_name: str | None = None
    evidence: list[AgronomicEvidence] = field(default_factory=list)
    context_version: str = ""
    contract_version: str = CONTRACT_VERSION
    recommendation_id: str | None = None
    validation_status: str = "validated"  # validated | repaired | fallback
    validation_issues: list[str] = field(default_factory=list)
    data_timestamps: dict = field(default_factory=dict)


class ChatAgent:
    def __init__(
        self,
        client: OpenAIChatClient | MockChatClient,
        context_builder: AssistantContextBuilder,
        language: str = "pt",
    ) -> None:
        self.client = client
        self.context_builder = context_builder
        self.language = language

    async def run(
        self,
        *,
        farm_id: str,
        sector_id: str | None,
        message: str,
        history: list[ChatTurn],
        access: AccessController,
        db: AsyncSession,
        prior_evidence: list[dict] | None = None,
    ) -> ChatResult:
        """Non-streaming entry point — the same orchestration, drained."""
        result: ChatResult | None = None
        async for event in self.run_events(
            farm_id=farm_id,
            sector_id=sector_id,
            message=message,
            history=history,
            access=access,
            db=db,
            prior_evidence=prior_evidence,
        ):
            if event.type == "done":
                result = event.payload["result"]
        assert result is not None  # run_events always ends with a done event
        return result

    async def run_events(
        self,
        *,
        farm_id: str,
        sector_id: str | None,
        message: str,
        history: list[ChatTurn],
        access: AccessController,
        db: AsyncSession,
        prior_evidence: list[dict] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        scope = ToolScope(farm_id=farm_id, sector_id=sector_id)
        session = ToolSession()

        yield ChatEvent("progress", {"stage": "context", "label": "A preparar o contexto…"})
        scope_ctx = await self._seed_scope_context(farm_id, sector_id, db)
        system = prompt_templates.CHAT_AGENT_SYSTEM_PT.format(
            scope_json=json.dumps(scope_ctx, ensure_ascii=False, default=str)
        )

        messages: list[dict] = [{"role": "system", "content": system}]
        for turn in history[-MAX_HISTORY_TURNS:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append(
            {
                "role": "user",
                "content": prompt_templates.wrap_user_message(message),
            }
        )

        proposed: ProposedAction | None = None
        # The selected sector's current decision is mandatory grounding, even
        # when the model elects not to read a tool itself.
        tool_calls: list[dict] = []
        if sector_id:
            current = await execute_tool(
                "get_sector_status",
                {"sector_id": sector_id},
                access=access,
                db=db,
                scope=scope,
                session=session,
            )
            tool_calls.append({"tool": "get_sector_status", "result": current})
            messages.append(
                {"role": "system", "content": json.dumps(current, ensure_ascii=False, default=str)}
            )
        last_content = ""
        exhausted = True

        for _ in range(MAX_ITERATIONS):
            resp = await self.client.run_tool_loop(messages, TOOL_SPECS)
            if not resp.tool_calls:
                last_content = resp.content or last_content or ""
                exhausted = False
                break
            last_content = resp.content or last_content
            messages.append(
                {
                    "role": "assistant",
                    "content": resp.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in resp.tool_calls
                    ],
                }
            )
            for tc in resp.tool_calls:
                # Tool ARGUMENTS never reach the user: they are model-authored and
                # unchecked. Only the fixed Portuguese stage label is emitted.
                yield ChatEvent(
                    "progress",
                    {
                        "stage": "tool",
                        "tool": tc.name,
                        "label": _TOOL_PROGRESS_PT.get(tc.name, _DEFAULT_PROGRESS_PT),
                    },
                )
                result = await execute_tool(
                    tc.name, tc.arguments, access=access, db=db, scope=scope, session=session
                )
                tool_calls.append(
                    {
                        "tool": tc.name,
                        "result": result,
                        "sector_id": tc.arguments.get("sector_id") or sector_id,
                    }
                )
                if proposed is None and "proposed_action" in result:
                    proposed = ProposedAction.model_validate(result["proposed_action"])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        facts = collect_facts(
            tool_calls,
            prior_evidence=prior_evidence,
            user_message=message,
            selected_sector_id=sector_id,
        )

        if exhausted:
            reply = deterministic_fallback_reply(facts)
            yield ChatEvent("answer", {"text": reply})
            yield ChatEvent(
                "done",
                {
                    "result": self._result(
                        reply,
                        proposed=proposed,
                        tool_calls=tool_calls,
                        facts=facts,
                        degraded=True,
                        validation_status="fallback",
                        issues=["tool_loop_exhausted"],
                    )
                },
            )
            return

        yield ChatEvent("progress", {"stage": "validating", "label": "A validar com os dados…"})
        reply, status, issues = await self._validated_reply(last_content, facts, messages)

        for block in _answer_blocks(reply):
            yield ChatEvent("answer", {"text": block})

        yield ChatEvent(
            "done",
            {
                "result": self._result(
                    reply,
                    proposed=proposed,
                    tool_calls=tool_calls,
                    facts=facts,
                    degraded=status == "fallback",
                    validation_status=status,
                    issues=issues,
                )
            },
        )

    async def _validated_reply(
        self,
        reply: str,
        facts: GroundedFacts,
        messages: list[dict],
    ) -> tuple[str, str, list[str]]:
        """Check, repair once, then fall back to engine outputs. Never publish unchecked."""
        validation = validate_reply(reply, facts)
        if validation.ok:
            return reply, "validated", []

        issues = [issue.detail for issue in validation.issues]
        for _ in range(MAX_REPAIRS):
            repair_messages = [
                *messages,
                {"role": "assistant", "content": reply},
                {"role": "user", "content": validation.repair_instruction()},
            ]
            try:
                repaired = await self.client.run_tool_loop(repair_messages, [])
            except Exception:
                break
            candidate = (repaired.content or "").strip()
            if not candidate:
                break
            validation = validate_reply(candidate, facts)
            reply = candidate
            if validation.ok:
                return reply, "repaired", issues
            issues.extend(issue.detail for issue in validation.issues)

        return deterministic_fallback_reply(facts), "fallback", issues

    def _result(
        self,
        reply: str,
        *,
        proposed: ProposedAction | None,
        tool_calls: list[dict],
        facts: GroundedFacts,
        degraded: bool,
        validation_status: str,
        issues: list[str],
    ) -> ChatResult:
        evidence_calls = [
            call
            for call in tool_calls
            if isinstance(call.get("result"), dict)
            and not call["result"].get("error")
            and call["tool"] != "get_field_observations"
        ]
        registry = build_evidence_registry(
            {
                "tool_results": {
                    "units": TOOL_MEASUREMENT_UNITS,
                    "items": [{call["tool"]: call["result"]} for call in evidence_calls],
                }
            }
        )
        scopes = None
        if facts.by_sector:
            scopes = {}
            for index, call in enumerate(evidence_calls):
                prefix = f"tool_results.items[{index}].{call['tool']}"
                if call["tool"] == "get_farm_overview":
                    for row_index, sector in enumerate(call["result"].get("sectors", [])):
                        scopes[f"{prefix}.sectors[{row_index}]"] = sector.get("name") or ""
                else:
                    sector_id = call["result"].get("sector_id") or call.get("sector_id")
                    scoped = facts.by_sector.get(sector_id)
                    scopes[prefix] = scoped.sector_name or "" if scoped else ""
        return ChatResult(
            reply=reply,
            proposed_action=proposed,
            degraded=degraded,
            model_name=getattr(self.client, "last_model", "mock"),
            evidence=select_chat_evidence(reply, registry, scopes=scopes),
            context_version=context_digest({"tools": tool_calls})[:32],
            recommendation_id=facts.recommendation_id,
            validation_status=validation_status,
            validation_issues=issues[:5],
            data_timestamps=collect_data_timestamps(tool_calls),
        )

    async def _seed_scope_context(
        self, farm_id: str, sector_id: str | None, db: AsyncSession
    ) -> dict:
        """Compact grounding context for the system prompt (best-effort)."""
        try:
            if sector_id:
                context = await self.context_builder.build_sector_ai_context(
                    sector_id, db, compact=True
                )
                scope = context.scope["sector"]
                decision = context.engine_decision
                water_balance = context.water_balance
                probe_quality = context.probe_state["data_quality"]
                return {
                    "schema_version": context.schema_version,
                    "sector_id": scope["id"],
                    "name": scope["name"],
                    "action": decision["action"],
                    "depletion_mm": water_balance["depletion_mm"],
                    "confidence_level": decision["confidence_level"],
                    "probe_data_quality": probe_quality,
                }
            ctx = await self.context_builder.build_farm_context(farm_id, db)
            return {
                "farm": ctx.farm_name,
                "sector_count": len(ctx.sectors),
                "active_alerts": ctx.total_active_alerts,
            }
        except Exception:
            return {"farm_id": farm_id, "sector_id": sector_id}


def _answer_blocks(reply: str) -> list[str]:
    """Split a validated reply into sentence-sized blocks for incremental delivery.

    The whole reply has already passed validation, so a block carries no claim the
    complete answer did not; splitting only decides how soon the reader sees it.
    """
    blocks = [block.strip() for block in _BLOCK_SPLIT_RE.split(reply or "") if block.strip()]
    return blocks or ([reply] if reply else [])
