"""High-level irrigation assistant service.

Composes context_builder + prompt_templates + LLM client into user-facing operations.
The LLM never accesses the DB — context_builder fetches everything first.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import prompt_templates
from app.ai.context_builder import (
    AssistantContextBuilder,
    FarmAssistantContext,
    build_sector_change_context,
)
from app.ai.evidence import EvidenceRegistry, build_evidence_registry
from app.ai.openai_client import MockChatClient, OpenAIChatClient
from app.ai.probe_signal import compute_probe_signal_stats
from app.metrics import ai_degraded_responses_total
from app.schemas.ai import (
    AgronomicCitation,
    AgronomicEvidence,
    AgronomicInterpretation,
    AgronomicInterpretationDraft,
)

logger = logging.getLogger(__name__)


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
        ctx = await self.context_builder.build_sector_ai_context(sector_id, db, compact=True)
        context_json = ctx.to_json()
        decision = ctx.engine_decision
        sector = ctx.scope["sector"]

        if decision["action"] is None:
            return (
                "Ainda não foi gerada uma recomendação para este sector. "
                "Por favor, clique em 'Gerar recomendação' primeiro."
            )

        system_prompt = prompt_templates.get_recommendation_template(self.language).format(
            context_json=context_json,
            user_notes=user_notes or "Nenhuma observação adicional.",
        )
        user_message = f"Analisa e explica a situação de rega para o sector '{sector['name']}'."
        return await self.client.complete(system_prompt, user_message)

    async def explain_recommendation_structured(
        self,
        sector_id: str,
        db: AsyncSession,
        user_notes: str | None = None,
    ) -> AgronomicInterpretation:
        ctx = await self.context_builder.build_sector_ai_context(sector_id, db, compact=True)
        context_json = ctx.to_json()
        decision = ctx.engine_decision
        sector = ctx.scope["sector"]

        if decision["action"] is None:
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
        user_message = f"Analisa e explica a situação de rega para o sector '{sector['name']}'."
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=json.loads(context_json),
            fallback_risk="medium",
            surface="recommendation",
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
        *,
        context: FarmAssistantContext | None = None,
    ) -> AgronomicInterpretation:
        ctx = context or await self.context_builder.build_farm_context(farm_id, db)
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
            surface="farm_summary",
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
            context_json=json.dumps(
                alert_data,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )
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
            context_json=json.dumps(
                alert_data,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )
        )
        user_message = f"Explica este alerta: {alert.title_pt}"
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=alert_data,
            fallback_risk=alert.severity
            if alert.severity in {"low", "medium", "high"}
            else "medium",
            max_tokens=700,
            surface="alert_explanation",
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
            line.lstrip("0123456789. )").strip() for line in lines if line and line[0].isdigit()
        ]
        return questions or [raw]

    async def diagnose_sector(self, sector_id: str, db: AsyncSession) -> str:
        """Root-cause diagnosis: WHY is this sector in its current hydric state."""
        ctx = await self.context_builder.build_sector_ai_context(sector_id, db, compact=False)
        context_json = ctx.to_json()
        sector = ctx.scope["sector"]

        system_prompt = prompt_templates.SECTOR_DIAGNOSIS_PT.format(context_json=context_json)
        user_message = f"Diagnostica as causas prováveis do estado hídrico actual do sector '{sector['name']}'."
        return await self.client.complete(system_prompt, user_message, max_tokens=600)

    async def diagnose_sector_structured(
        self,
        sector_id: str,
        db: AsyncSession,
    ) -> AgronomicInterpretation:
        ctx = await self.context_builder.build_sector_ai_context(sector_id, db, compact=False)
        context_json = ctx.to_json()
        sector = ctx.scope["sector"]

        system_prompt = prompt_templates.SECTOR_DIAGNOSIS_PT.format(context_json=context_json)
        user_message = f"Diagnostica as causas prováveis do estado hídrico actual do sector '{sector['name']}'."
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=json.loads(context_json),
            fallback_risk="medium",
            max_tokens=600,
            surface="sector_diagnosis",
        )

    async def interpret_probe_patterns(self, probe_id: str, db: AsyncSession) -> str:
        """Interpret time-series probe signal patterns."""
        stats = await compute_probe_signal_stats(probe_id, db)
        if "error" in stats:
            return "Sonda não encontrada ou sem dados suficientes para análise."

        signal_json = json.dumps(
            stats,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        system_prompt = prompt_templates.PROBE_INTERPRETATION_PT.format(signal_json=signal_json)
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

        signal_json = json.dumps(
            stats,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        system_prompt = prompt_templates.PROBE_ADVISORY_PT.format(signal_json=signal_json)
        user_message = (
            f"Interpreta o comportamento da sonda '{stats.get('probe_external_id', probe_id)}' "
            f"no sector '{stats.get('sector_name', '')}'."
        )
        structured = await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context={"probe_signal": stats},
            fallback_risk="medium",
            max_tokens=700,
            surface="probe_diagnosis",
        )
        return self._apply_probe_recommendation_guard(stats, structured)

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
            try:
                structured = await self.context_builder.build_sector_ai_context(
                    sector_id, db, compact=False
                )
                context_json = structured.to_json()
            except Exception:
                base_ctx = await self.context_builder.build_sector_context(sector_id, db)
                context_json = self.context_builder.to_json(base_ctx)
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
            + "(p.ex. probe_state.latest_readings, weather.forecast, "
            + "irrigation_execution.manual_events) e identifica explicitamente "
            + "alerts_and_limitations.known_limitations quando "
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
            try:
                structured = await self.context_builder.build_sector_ai_context(
                    sector_id, db, compact=False
                )
                context_obj = structured.to_dict()
                context_json = structured.to_json()
            except Exception:
                base_ctx = await self.context_builder.build_sector_context(sector_id, db)
                base_json = self.context_builder.to_json(base_ctx)
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
            surface="chat_structured",
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

        context_json = json.dumps(
            context,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        system_prompt = prompt_templates.SECTOR_CHANGE_ANALYSIS_PT.format(context_json=context_json)
        sector_name = context.get("sector", {}).get("name", sector_id)
        user_message = f"Explica o que mudou no sector '{sector_name}' nas últimas {context['window_hours']} horas."
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            context=context,
            fallback_risk="medium",
            max_tokens=800,
            surface="change_analysis",
        )

    async def analyze_irrigation_effectiveness(
        self,
        sector_id: str,
        db: AsyncSession,
    ) -> AgronomicInterpretation:
        context = (
            await self.context_builder.build_sector_ai_context(
                sector_id,
                db,
                compact=False,
            )
        ).to_dict()
        relevant = {
            key: context[key]
            for key in (
                "scope",
                "engine_decision",
                "probe_state",
                "irrigation_execution",
                "outcomes",
                "alerts_and_limitations",
            )
        }
        context_json = json.dumps(
            relevant,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        system_prompt = prompt_templates.IRRIGATION_EFFECTIVENESS_PT.format(
            context_json=context_json
        )
        return await self._complete_structured(
            system_prompt=system_prompt,
            user_message="Explica a eficácia das regas recentes deste sector.",
            context=relevant,
            fallback_risk="medium",
            max_tokens=800,
            surface="irrigation_effectiveness",
        )

    def _apply_probe_recommendation_guard(
        self,
        stats: dict,
        interpretation: AgronomicInterpretation,
    ) -> AgronomicInterpretation:
        """Keep probe advice consistent with the latest engine water-balance decision.

        Probe-pattern interpretation is useful for diagnosing sensor behaviour, but it
        must not override a fresh sector recommendation that says there is no deficit.
        """
        latest = stats.get("latest_recommendation")
        if not isinstance(latest, dict):
            return interpretation

        action = str(latest.get("action") or "")
        depletion_pct = latest.get("depletion_pct")
        depletion_mm = latest.get("depletion_mm")

        try:
            depletion_pct_f = float(depletion_pct) if depletion_pct is not None else None
        except (TypeError, ValueError):
            depletion_pct_f = None
        try:
            depletion_mm_f = float(depletion_mm) if depletion_mm is not None else None
        except (TypeError, ValueError):
            depletion_mm_f = None

        # "skip"/"defer" are the engine's two "do not irrigate now" decisions
        # (the RecommendationAction enum has no "no_irrigation" value). The
        # depletion floors are a secondary guard for near-saturation cases.
        engine_says_no_irrigation = (
            action in ("skip", "defer")
            or (depletion_pct_f is not None and depletion_pct_f <= 5.0)
            or (depletion_mm_f is not None and depletion_mm_f <= 1.0)
        )
        if not engine_says_no_irrigation:
            return interpretation

        # Surgical override: keep the LLM's depth description (summary + depth
        # evidence) but neutralise the irrigation advice so it can never contradict
        # the engine's "do not irrigate" decision.
        interpretation.risk_level = "low"
        interpretation.irrigation_advice = (
            "Não regues agora — o balanço hídrico tem reserva suficiente. Vigia a evolução das "
            "camadas mais fundas e confirma sensores com leituras díspares."
        )
        interpretation.recommended_actions = [
            "Monitorizar a tendência das camadas mais fundas nas próximas 24-48 horas.",
            "Confirmar qualquer profundidade com leitura discrepante antes de alterar a rega.",
        ]
        interpretation.confidence_score = max(interpretation.confidence_score, 0.75)
        interpretation.confidence_explanation = (
            "Conselho alinhado com a recomendação mais recente do motor (não regar)."
        )

        # Prepend server-resolved engine evidence; never manufacture a display value.
        registry = build_evidence_registry({"probe_signal": stats})
        engine_evidence = registry.evidence_for_paths(
            ["probe_signal.latest_recommendation.action"], limit=1
        )
        evidence = list(interpretation.evidence)
        for item in reversed(engine_evidence):
            if all(ev.evidence_id != item.evidence_id for ev in evidence):
                evidence.insert(0, item)
        interpretation.evidence = evidence[:4]
        return interpretation

    async def _complete_structured(
        self,
        *,
        system_prompt: str,
        user_message: str,
        context: dict | list | None,
        fallback_risk: str = "medium",
        max_tokens: int = 900,
        surface: str = "structured",
    ) -> AgronomicInterpretation:
        registry = build_evidence_registry(context)
        system_prompt = (
            system_prompt
            + prompt_templates.get_structured_output_contract(self.language)
            + "\n\nREGISTO DE EVIDÊNCIA PERMITIDA (ID: caminho):\n"
            + registry.prompt_catalog()
        )
        try:
            parsed = await self.client.complete_structured(
                system_prompt,
                user_message,
                AgronomicInterpretationDraft,
                max_tokens=max_tokens,
                temperature=0.1,
                surface=surface,
            )
        except Exception as exc:
            logger.exception(
                "Structured AI completion failed; serving grounded fallback",
                extra={"surface": surface, "error_type": type(exc).__name__},
            )
            ai_degraded_responses_total.labels(
                surface,
                type(exc).__name__,
            ).inc()
            return self._fallback_structured(
                "",
                context=context,
                risk_level=fallback_risk,
                confidence_score=0.3,
                degraded=True,
                error_code="llm_unavailable",
            )

        result = self._resolve_model_interpretation(parsed, registry, context)
        if not result.evidence:
            result.evidence = self._default_evidence(context, registry=registry)
        if not result.missing_data:
            result.missing_data = self._known_limitations(context)
        return result

    def _resolve_model_interpretation(
        self,
        parsed,
        registry: EvidenceRegistry,
        context: dict | list | None,
    ) -> AgronomicInterpretation:
        """Resolve model citations and discard every unregistered reference."""
        if isinstance(parsed, AgronomicInterpretationDraft):
            draft = parsed
            citations = draft.evidence
        elif isinstance(parsed, AgronomicInterpretation):
            # Compatibility with test doubles and cached pre-P2 model objects. Values
            # supplied by these objects are ignored; only resolvable paths survive.
            citations = self._legacy_citations(parsed, registry, context)
            draft = AgronomicInterpretationDraft.model_validate(
                {
                    **parsed.model_dump(exclude={"evidence"}),
                    "evidence": [citation.model_dump() for citation in citations],
                }
            )
        else:
            draft = AgronomicInterpretationDraft.model_validate(parsed)
            citations = draft.evidence

        return AgronomicInterpretation(
            **draft.model_dump(exclude={"evidence"}),
            evidence=registry.resolve_citations(citations),
        )

    def _legacy_citations(
        self,
        parsed: AgronomicInterpretation,
        registry: EvidenceRegistry,
        context: dict | list | None,
    ) -> list[AgronomicCitation]:
        citations: list[AgronomicCitation] = []
        root_prefix = None
        if isinstance(context, dict) and len(context) == 1:
            root_prefix = next(iter(context))
        for evidence in parsed.evidence:
            entry = registry.first_entry_under(evidence.source)
            if entry is None and root_prefix:
                entry = registry.first_entry_under(f"{root_prefix}.{evidence.source}")
            if entry is not None:
                citations.append(AgronomicCitation(evidence_id=entry.evidence_id))
        return citations

    def _fallback_structured(
        self,
        text: str,
        *,
        context: dict | list | None,
        risk_level: str = "medium",
        confidence_score: float | None = None,
        degraded: bool = False,
        error_code: str | None = None,
    ) -> AgronomicInterpretation:
        evidence = self._default_evidence(context)
        missing_data = self._known_limitations(context)
        return AgronomicInterpretation(
            summary=text.strip() or "Sem análise disponível.",
            risk_level=risk_level,  # type: ignore[arg-type]
            irrigation_advice=text.strip() or "Sem conselho de rega disponível.",
            evidence=evidence,
            missing_data=missing_data,
            confidence_score=confidence_score
            if confidence_score is not None
            else (0.65 if evidence else 0.35),
            confidence_explanation=(
                "Resposta validada com evidência do contexto estruturado."
                if evidence
                else "Resposta gerada com contexto limitado; confirma os dados antes de actuar."
            ),
            recommended_actions=self._default_actions(context),
            degraded=degraded,
            error_code=error_code,
        )

    def render_structured(self, interpretation: AgronomicInterpretation) -> str:
        lines: list[str] = []
        used: set[str] = set()

        for ev in interpretation.evidence[:6]:
            label = ev.label
            if label not in used:
                lines.append(f"• {label}: {ev.value}")
                used.add(label)

        if not lines:
            lines.append(f"• {interpretation.summary}")

        if interpretation.risk_level in ("high", "critical") and "Atenção" not in used:
            msg = (
                interpretation.missing_data[0]
                if interpretation.missing_data
                else interpretation.irrigation_advice
            )
            lines.append(f"• Atenção: {msg}")

        if interpretation.confidence_score < 0.60:
            pct = round(interpretation.confidence_score * 100)
            lines.append(
                f"• Baixa confiança: A confiança na recomendação é de {pct}%"
                f" — {interpretation.confidence_explanation}"
            )

        return "\n".join(lines)

    def render_probe_interpretation(self, interpretation: AgronomicInterpretation) -> str:
        """Render probe diagnosis for the existing probe card UI.

        The probe card expects compact bullet lines with a stable "Label: value"
        shape. Keep this separate from render_structured(), which is evidence-led
        and intentionally omits the summary when evidence exists.
        """
        lines: list[str] = []

        summary = interpretation.summary.strip()
        advice = interpretation.irrigation_advice.strip()
        if summary:
            lines.append(f"• Perfil da sonda: {summary}")
        if advice and advice != summary:
            lines.append(f"• Conselho: {advice}")

        evidence_values: list[str] = []
        seen_evidence: set[str] = set()
        for ev in interpretation.evidence:
            value = ev.value.strip()
            if value and value not in seen_evidence:
                evidence_values.append(value)
                seen_evidence.add(value)
            if len(evidence_values) >= 3:
                break
        if evidence_values:
            lines.append(f"• Sinais observados: {'; '.join(evidence_values)}")

        actions = [a.strip() for a in interpretation.recommended_actions if a.strip()]
        if actions:
            lines.append(f"• Próxima verificação: {'; '.join(actions[:2])}")

        if interpretation.missing_data:
            missing = "; ".join(m.strip() for m in interpretation.missing_data[:2] if m.strip())
            if missing:
                lines.append(f"• Limitações: {missing}")

        if interpretation.confidence_score < 0.60:
            pct = round(interpretation.confidence_score * 100)
            lines.append(f"• Confiança: {pct}% — {interpretation.confidence_explanation}")

        return "\n".join(lines) if lines else "• Perfil da sonda: Sem análise disponível."

    def _default_evidence(
        self,
        context: dict | list | None,
        *,
        registry: EvidenceRegistry | None = None,
    ) -> list[AgronomicEvidence]:
        registry = registry or build_evidence_registry(context)
        preferred = [
            "engine_decision.action",
            "water_balance.depletion_mm",
            "water_balance.etc_mm",
            "weather.forecast[0].rainfall_mm",
            "probe_state.data_quality.fresh_depths",
            "probe_signal.latest_recommendation.action",
            "probe_signal.depths[0].humidade_actual",
            "outcomes.latest.status",
            "alert.severity",
            "recommendation_history[0].action",
            "sectors[0].recommendation_action",
        ]
        evidence = registry.evidence_for_paths(preferred)
        if evidence:
            return evidence
        return [entry.to_evidence() for entry in registry.entries[:4]]

    def _known_limitations(self, context: dict | list | None) -> list[str]:
        if not isinstance(context, dict):
            return []
        limitations = context.get("known_limitations")
        if isinstance(limitations, list):
            return [str(item) for item in limitations[:5]]
        limitations = _get_path(context, ["alerts_and_limitations", "known_limitations"])
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
