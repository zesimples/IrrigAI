"""High-level irrigation assistant service.

Composes context_builder + prompt_templates + LLM client into user-facing operations.
The LLM never accesses the DB — context_builder fetches everything first.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context_builder import (
    AssistantContextBuilder,
    build_sector_change_context,
    build_structured_agronomic_context,
)
from app.ai.openai_client import MockChatClient, OpenAIChatClient
from app.ai import prompt_templates
from app.ai.probe_signal import compute_probe_signal_stats
from app.schemas.ai import AgronomicEvidence, AgronomicInterpretation


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

    async def explain_recommendation_structured(
        self,
        sector_id: str,
        db: AsyncSession,
        user_notes: str | None = None,
    ) -> AgronomicInterpretation:
        ctx = await self.context_builder.build_sector_context(sector_id, db)
        context_json = self.context_builder.to_json(ctx)

        if ctx.recommendation_action is None:
            return self._fallback_structured(
                "Ainda não foi gerada uma recomendação para este sector.",
                context={"known_limitations": ["No recommendation generated for this sector."]},
                risk_level="medium",
                confidence_score=0.3,
            )

        system_prompt = prompt_templates.get_recommendation_template(self.language).format(
            context_json=context_json,
            user_notes=user_notes or "Nenhuma observação adicional.",
        )
        user_message = (
            f"Analisa e explica a situação de rega para o sector '{ctx.sector_name}'."
        )
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=json.loads(context_json),
            fallback_risk="medium",
        )

    async def summarize_farm(self, farm_id: str, db: AsyncSession) -> str:
        """Produce a daily farm status summary."""
        ctx = await self.context_builder.build_farm_context(farm_id, db)
        context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.get_farm_summary_template(self.language).format(
            context_json=context_json
        )
        user_message = f"Faz um resumo do estado da exploração '{ctx.farm_name}' para hoje."
        return await self.client.complete(system_prompt, user_message, max_tokens=800)

    async def summarize_farm_structured(
        self,
        farm_id: str,
        db: AsyncSession,
    ) -> AgronomicInterpretation:
        ctx = await self.context_builder.build_farm_context(farm_id, db)
        context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.get_farm_summary_template(self.language).format(
            context_json=context_json
        )
        user_message = f"Faz um resumo do estado da exploração '{ctx.farm_name}' para hoje."
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=json.loads(context_json),
            fallback_risk="medium",
            max_tokens=800,
        )

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

    async def explain_anomaly_structured(
        self,
        alert_id: str,
        db: AsyncSession,
    ) -> AgronomicInterpretation:
        """Explain an active alert with validated structured evidence."""
        from app.models import Alert

        alert = await db.get(Alert, alert_id)
        if alert is None:
            return self._fallback_structured(
                "Alerta não encontrado.",
                context={"known_limitations": ["Alert not found."]},
                risk_level="medium",
                confidence_score=0.2,
            )

        alert_data = {
            "alert": {
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "title": alert.title_pt,
                "description": alert.description_pt,
                "data": alert.data or {},
            }
        }
        system_prompt = prompt_templates.ANOMALY_EXPLANATION_PT.format(
            context_json=json.dumps(alert_data, ensure_ascii=False, default=str, indent=2)
        )
        user_message = f"Explica este alerta: {alert.title_pt}"
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=alert_data,
            fallback_risk=alert.severity if alert.severity in {"low", "medium", "high"} else "medium",
            max_tokens=700,
        )

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

    async def diagnose_sector(self, sector_id: str, db: AsyncSession) -> str:
        """Root-cause diagnosis: WHY is this sector in its current hydric state."""
        ctx = await self.context_builder.build_sector_context(sector_id, db)
        context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.SECTOR_DIAGNOSIS_PT.format(
            context_json=context_json
        )
        user_message = (
            f"Diagnostica as causas prováveis do estado hídrico actual do sector '{ctx.sector_name}'."
        )
        return await self.client.complete(system_prompt, user_message, max_tokens=600)

    async def diagnose_sector_structured(
        self,
        sector_id: str,
        db: AsyncSession,
    ) -> AgronomicInterpretation:
        ctx = await self.context_builder.build_sector_context(sector_id, db)
        context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.SECTOR_DIAGNOSIS_PT.format(
            context_json=context_json
        )
        user_message = (
            f"Diagnostica as causas prováveis do estado hídrico actual do sector '{ctx.sector_name}'."
        )
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=json.loads(context_json),
            fallback_risk="medium",
            max_tokens=600,
        )

    async def interpret_probe_patterns(self, probe_id: str, db: AsyncSession) -> str:
        """Interpret time-series probe signal patterns."""
        stats = await compute_probe_signal_stats(probe_id, db)
        if "error" in stats:
            return "Sonda não encontrada ou sem dados suficientes para análise."

        signal_json = json.dumps(stats, ensure_ascii=False, default=str, indent=2)
        system_prompt = prompt_templates.PROBE_INTERPRETATION_PT.format(
            signal_json=signal_json
        )
        user_message = (
            f"Interpreta o comportamento da sonda '{stats.get('probe_external_id', probe_id)}' "
            f"no sector '{stats.get('sector_name', '')}'."
        )
        return await self.client.complete(system_prompt, user_message, max_tokens=700)

    async def interpret_probe_patterns_structured(
        self,
        probe_id: str,
        db: AsyncSession,
    ) -> AgronomicInterpretation:
        stats = await compute_probe_signal_stats(probe_id, db)
        if "error" in stats:
            return self._fallback_structured(
                "Sonda não encontrada ou sem dados suficientes para análise.",
                context={"known_limitations": ["Probe not found or insufficient signal data."]},
                risk_level="medium",
                confidence_score=0.2,
            )

        signal_json = json.dumps(stats, ensure_ascii=False, default=str, indent=2)
        system_prompt = prompt_templates.PROBE_INTERPRETATION_PT.format(
            signal_json=signal_json
        )
        user_message = (
            f"Interpreta o comportamento da sonda '{stats.get('probe_external_id', probe_id)}' "
            f"no sector '{stats.get('sector_name', '')}'."
        )
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context={"probe_signal": stats},
            fallback_risk="medium",
            max_tokens=700,
        )

    async def chat(
        self,
        farm_id: str,
        user_message: str,
        db: AsyncSession,
        sector_id: str | None = None,
    ) -> str:
        """Free-form chat about the farm or a specific sector.

        When a sector_id is available we attach the full structured agronomic
        context (probes, water events, weather, history, limitations) so the
        LLM can cite evidence rather than hallucinate.
        """
        if sector_id:
            base_ctx = await self.context_builder.build_sector_context(sector_id, db)
            base_json = self.context_builder.to_json(base_ctx)
            try:
                structured = await build_structured_agronomic_context(sector_id, db)
                structured_json = json.dumps(
                    structured, ensure_ascii=False, default=str, indent=2
                )
                context_json = (
                    base_json
                    + "\n\n# STRUCTURED AGRONOMIC CONTEXT (cite by JSON path)\n"
                    + structured_json
                )
            except Exception:
                # Structured context is best-effort; never break chat.
                context_json = base_json
        else:
            ctx = await self.context_builder.build_farm_context(farm_id, db)
            context_json = self.context_builder.to_json(ctx)

        system_prompt = prompt_templates.CHAT_QA_PT.format(
            context_json=context_json,
            user_message=user_message,
        )
        # Instruct the model to cite evidence keys from the structured context.
        system_prompt = (
            system_prompt
            + "\n\nNota: quando a STRUCTURED AGRONOMIC CONTEXT estiver disponível, "
            + "fundamenta cada afirmação com referência ao caminho JSON exacto "
            + "(p.ex. probe_summary.latest_readings, weather.forecast, water_events) "
            + "e identifica explicitamente os campos em known_limitations quando "
            + "responderes sobre fiabilidade."
        )
        return await self.client.complete(system_prompt, user_message, max_tokens=700)

    async def chat_structured(
        self,
        farm_id: str,
        user_message: str,
        db: AsyncSession,
        sector_id: str | None = None,
    ) -> AgronomicInterpretation:
        if sector_id:
            base_ctx = await self.context_builder.build_sector_context(sector_id, db)
            base_json = self.context_builder.to_json(base_ctx)
            try:
                structured = await build_structured_agronomic_context(sector_id, db)
                structured_json = json.dumps(
                    structured, ensure_ascii=False, default=str, indent=2
                )
                context_json = (
                    base_json
                    + "\n\n# STRUCTURED AGRONOMIC CONTEXT (cite by JSON path)\n"
                    + structured_json
                )
                context_obj = structured
            except Exception:
                context_json = base_json
                context_obj = json.loads(base_json)
        else:
            ctx = await self.context_builder.build_farm_context(farm_id, db)
            context_json = self.context_builder.to_json(ctx)
            context_obj = json.loads(context_json)

        system_prompt = prompt_templates.CHAT_QA_PT.format(
            context_json=context_json,
            user_message=user_message,
        )
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=context_obj,
            fallback_risk="medium",
            max_tokens=700,
        )

    async def analyze_sector_changes(
        self,
        sector_id: str,
        db: AsyncSession,
        window_hours: int = 72,
    ) -> AgronomicInterpretation:
        context = await build_sector_change_context(
            sector_id=sector_id,
            db=db,
            window_hours=window_hours,
        )
        if context.get("error"):
            return self._fallback_structured(
                "Sector não encontrado para análise de alterações.",
                context=context,
                risk_level="medium",
                confidence_score=0.2,
            )

        context_json = json.dumps(context, ensure_ascii=False, default=str, indent=2)
        system_prompt = prompt_templates.SECTOR_CHANGE_ANALYSIS_PT.format(
            context_json=context_json
        )
        sector_name = context.get("sector", {}).get("name", sector_id)
        user_message = (
            f"Explica o que mudou no sector '{sector_name}' nas últimas {context['window_hours']} horas."
        )
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=context,
            fallback_risk="medium",
            max_tokens=800,
        )

    async def _complete_structured(
        self,
        *,
        system_prompt: str,
        user_message: str,
        context: dict | list | None,
        fallback_risk: str = "medium",
        max_tokens: int = 900,
    ) -> AgronomicInterpretation:
        structured_prompt = system_prompt + "\n\n" + prompt_templates.STRUCTURED_OUTPUT_PT
        raw = await self.client.complete(
            structured_prompt,
            user_message,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        parsed = self._parse_structured_output(raw)
        if parsed is None:
            parsed = self._fallback_structured(
                raw,
                context=context,
                risk_level=fallback_risk,
            )

        if not parsed.evidence:
            parsed.evidence = self._default_evidence(context)
        if not parsed.missing_data:
            parsed.missing_data = self._known_limitations(context)
        return parsed

    def _parse_structured_output(self, raw: str) -> AgronomicInterpretation | None:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            return AgronomicInterpretation.model_validate(json.loads(text))
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                return AgronomicInterpretation.model_validate(json.loads(text[start:end + 1]))
            except Exception:
                return None

    def _fallback_structured(
        self,
        text: str,
        *,
        context: dict | list | None,
        risk_level: str = "medium",
        confidence_score: float | None = None,
    ) -> AgronomicInterpretation:
        evidence = self._default_evidence(context)
        missing_data = self._known_limitations(context)
        return AgronomicInterpretation(
            summary=text.strip() or "Sem análise disponível.",
            risk_level=risk_level,  # type: ignore[arg-type]
            irrigation_advice=text.strip() or "Sem conselho de rega disponível.",
            evidence=evidence,
            missing_data=missing_data,
            confidence_score=confidence_score if confidence_score is not None else (0.65 if evidence else 0.35),
            confidence_explanation=(
                "Resposta validada com evidência do contexto estruturado."
                if evidence
                else "Resposta gerada com contexto limitado; confirma os dados antes de actuar."
            ),
            recommended_actions=self._default_actions(context),
        )

    def render_structured(self, interpretation: AgronomicInterpretation) -> str:
        actions = "; ".join(interpretation.recommended_actions[:3])
        evidence = "; ".join(f"{e.source}: {e.value}" for e in interpretation.evidence[:3])
        parts = [
            interpretation.summary,
            f"Conselho: {interpretation.irrigation_advice}",
            f"Confiança: {interpretation.confidence_score:.0%} — {interpretation.confidence_explanation}",
        ]
        if actions:
            parts.append(f"Acções: {actions}")
        if evidence:
            parts.append(f"Evidência: {evidence}")
        return "\n".join(parts)

    def _default_evidence(self, context: dict | list | None) -> list[AgronomicEvidence]:
        if not isinstance(context, dict):
            return []
        candidates: list[tuple[str, object]] = [
            ("probe_summary.data_quality", _get_path(context, ["probe_summary", "data_quality"])),
            ("probe_summary.latest_readings", _get_path(context, ["probe_summary", "latest_readings"])),
            ("water_events", context.get("water_events")),
            ("water_event_changes", context.get("water_event_changes")),
            ("water_balance", context.get("water_balance")),
            ("current_context_summary.water_balance", _get_path(context, ["current_context_summary", "water_balance"])),
            ("recommendation_history", context.get("recommendation_history")),
            ("recommendation_change", context.get("recommendation_change")),
            ("weather.forecast", _get_path(context, ["weather", "forecast"])),
            ("weather_changes.observations", _get_path(context, ["weather_changes", "observations"])),
            ("alert", context.get("alert")),
            ("known_limitations", context.get("known_limitations")),
            ("probe_signal", context.get("probe_signal")),
        ]
        evidence: list[AgronomicEvidence] = []
        for source, value in candidates:
            if value in (None, [], {}):
                continue
            evidence.append(AgronomicEvidence(source=source, value=_compact_value(value)))
            if len(evidence) >= 4:
                break
        return evidence

    def _known_limitations(self, context: dict | list | None) -> list[str]:
        if not isinstance(context, dict):
            return []
        limitations = context.get("known_limitations")
        if isinstance(limitations, list):
            return [str(item) for item in limitations[:5]]
        missing_config = context.get("missing_config")
        if isinstance(missing_config, list):
            return [str(item) for item in missing_config[:5]]
        return []

    def _default_actions(self, context: dict | list | None) -> list[str]:
        limitations = self._known_limitations(context)
        if limitations:
            return [f"Corrigir/confirmar: {item}" for item in limitations[:3]]
        return ["Validar a recomendação com observação de campo antes de alterar a rega."]


def _get_path(data: dict, path: list[str]) -> object | None:
    current: object = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _compact_value(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 260 else text[:257] + "..."
