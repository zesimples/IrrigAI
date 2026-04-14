"""High-level irrigation assistant service.

Composes context_builder + prompt_templates + LLM client into user-facing operations.
The LLM never accesses the DB — context_builder fetches everything first.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient, OpenAIChatClient
from app.ai import prompt_templates


class IrrigationAssistant:
    def __init__(
        self,
        context_builder: AssistantContextBuilder,
        client: OpenAIChatClient | MockChatClient,
        language: str = "pt",
    ) -> None:
        self.context_builder = context_builder
        self.client = client
        self.language = language

    async def explain_recommendation(
        self,
        sector_id: str,
        db: AsyncSession,
        user_notes: str | None = None,
    ) -> str:
        """Explain the latest recommendation for a sector in natural language.

        If user_notes is provided (field observations, agronomist context), they
        are appended to the prompt so the AI can incorporate them into its analysis.
        """
        ctx = await self.context_builder.build_sector_context(sector_id, db)
        context_json = self.context_builder.to_json(ctx)

        if ctx.recommendation_action is None:
            return (
                "Ainda não foi gerada uma recomendação para este sector. "
                "Por favor, clique em 'Gerar recomendação' primeiro."
            )

        system_prompt = prompt_templates.get_recommendation_template(self.language).format(
            context_json=context_json,
            user_notes=user_notes or "Nenhuma observação adicional.",
        )
        user_message = (
            f"Analisa e explica a situação de rega para o sector '{ctx.sector_name}'."
        )
        return await self.client.complete(system_prompt, user_message)

    async def summarize_farm(self, farm_id: str, db: AsyncSession) -> str:
        """Produce a daily farm status summary."""
        ctx = await self.context_builder.build_farm_context(farm_id, db)
        context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.get_farm_summary_template(self.language).format(
            context_json=context_json
        )
        user_message = f"Faz um resumo do estado da exploração '{ctx.farm_name}' para hoje."
        return await self.client.complete(system_prompt, user_message, max_tokens=800)

    async def explain_anomaly(self, alert_id: str, db: AsyncSession) -> str:
        """Explain an active alert in natural language."""
        from app.models import Alert

        alert = await db.get(Alert, alert_id)
        if alert is None:
            return "Alerta não encontrado."

        alert_data = {
            "alert_id": alert.id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "title": alert.title_pt,
            "description": alert.description_pt,
            "data": alert.data or {},
        }

        system_prompt = prompt_templates.ANOMALY_EXPLANATION_PT.format(
            context_json=json.dumps(alert_data, ensure_ascii=False, default=str, indent=2)
        )
        user_message = f"Explica este alerta: {alert.title_pt}"
        return await self.client.complete(system_prompt, user_message)

    async def generate_missing_data_questions(self, farm_id: str, db: AsyncSession) -> list[str]:
        """Return prioritised questions to improve recommendation confidence."""
        ctx = await self.context_builder.build_farm_context(farm_id, db)
        context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.get_missing_data_template(self.language).format(
            context_json=context_json
        )
        user_message = "Que perguntas devo fazer ao agricultor para melhorar as recomendações?"

        raw = await self.client.complete(system_prompt, user_message, max_tokens=500)

        # Parse numbered list into individual strings
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        questions = [
            line.lstrip("0123456789. )").strip()
            for line in lines
            if line and line[0].isdigit()
        ]
        return questions or [raw]

    async def chat(
        self,
        farm_id: str,
        user_message: str,
        db: AsyncSession,
        sector_id: str | None = None,
    ) -> str:
        """Free-form chat about the farm or a specific sector."""
        if sector_id:
            ctx = await self.context_builder.build_sector_context(sector_id, db)
            context_json = self.context_builder.to_json(ctx)
        else:
            ctx = await self.context_builder.build_farm_context(farm_id, db)
            context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.CHAT_QA_PT.format(
            context_json=context_json,
            user_message=user_message,
        )
        return await self.client.complete(system_prompt, user_message, max_tokens=700)
