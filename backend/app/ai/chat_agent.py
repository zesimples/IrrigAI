"""Agentic chat loop: history + tools, prose output, propose-only writes."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.access import AccessController
from app.ai import prompt_templates
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient, OpenAIChatClient
from app.ai.tools import TOOL_SPECS, ToolScope, execute_tool
from app.schemas.ai import ChatTurn, ProposedAction

MAX_HISTORY_TURNS = 8
MAX_ITERATIONS = 4


@dataclass
class ChatResult:
    reply: str
    proposed_action: ProposedAction | None = None


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
    ) -> ChatResult:
        scope = ToolScope(farm_id=farm_id, sector_id=sector_id)
        scope_ctx = await self._seed_scope_context(farm_id, sector_id, db)
        system = prompt_templates.CHAT_AGENT_SYSTEM_PT.format(
            scope_json=json.dumps(scope_ctx, ensure_ascii=False, default=str)
        )

        messages: list[dict] = [{"role": "system", "content": system}]
        for turn in history[-MAX_HISTORY_TURNS:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        proposed: ProposedAction | None = None
        last_content = ""

        for _ in range(MAX_ITERATIONS):
            resp = await self.client.run_tool_loop(messages, TOOL_SPECS)
            if not resp.tool_calls:
                return ChatResult(reply=resp.content or last_content or "", proposed_action=proposed)
            last_content = resp.content or last_content
            messages.append({
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
            })
            for tc in resp.tool_calls:
                result = await execute_tool(tc.name, tc.arguments, access=access, db=db, scope=scope)
                if proposed is None and "proposed_action" in result:
                    proposed = ProposedAction.model_validate(result["proposed_action"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        return ChatResult(
            reply=last_content or "Não consegui concluir a resposta. Tenta reformular.",
            proposed_action=proposed,
        )

    async def _seed_scope_context(
        self, farm_id: str, sector_id: str | None, db: AsyncSession
    ) -> dict:
        """Compact grounding context for the system prompt (best-effort)."""
        try:
            if sector_id:
                s = await self.context_builder.build_sector_context(sector_id, db)
                return {
                    "sector_id": s.sector_id,
                    "name": s.sector_name,
                    "action": s.recommendation_action,
                    "depletion_mm": s.rootzone_depletion_mm,
                    "confidence_level": s.confidence_level,
                    "source_confidence": s.source_confidence,
                }
            ctx = await self.context_builder.build_farm_context(farm_id, db)
            return {
                "farm": ctx.farm_name,
                "sector_count": len(ctx.sectors),
                "active_alerts": ctx.total_active_alerts,
            }
        except Exception:
            return {"farm_id": farm_id, "sector_id": sector_id}
