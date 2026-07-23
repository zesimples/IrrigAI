"""OpenAI ChatGPT client for irrigation assistant.

Provides OpenAIChatClient (real API) and MockChatClient (testing without key).
Use get_chat_client(settings) to obtain the right instance.
"""

import json as _json
import logging
import re as _re
from dataclasses import dataclass, field

import openai
from pydantic import BaseModel

from app.config import Settings
from app.metrics import ai_requests_total, ai_tokens_input_total, ai_tokens_output_total
from app.schemas.ai import AgronomicEvidence, AgronomicInterpretation

logger = logging.getLogger(__name__)


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMToolResponse:
    content: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)


class LLMRefusalError(Exception):
    """Raised when the model refuses to produce structured output."""


class OpenAIChatClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        *,
        models: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ):
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self.model = model
        self.models = models or {}
        self.last_model = model

    def model_for_surface(self, surface: str) -> str:
        model = self.models.get(surface)
        if not model and surface != "chat":
            model = self.models.get("structured")
        return model or self.model

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
        surface: str = "general",
    ) -> str:
        model = self.model_for_surface(surface)
        self.last_model = model
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = response.usage
            if usage:
                ai_tokens_input_total.labels("openai", model).inc(usage.prompt_tokens)
                ai_tokens_output_total.labels("openai", model).inc(usage.completion_tokens)
                logger.debug(
                    "openai_usage",
                    extra={
                        "model": model,
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                    },
                )
            ai_requests_total.labels("openai", model, "success").inc()
            return response.choices[0].message.content or ""
        except Exception:
            ai_requests_total.labels("openai", model, "failure").inc()
            raise

    async def complete_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema_model: type[BaseModel],
        *,
        max_tokens: int = 900,
        temperature: float = 0.1,
        surface: str = "structured",
    ) -> BaseModel:
        model = self.model_for_surface(surface)
        self.last_model = model
        try:
            response = await self.client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format=schema_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = response.usage
            if usage:
                ai_tokens_input_total.labels("openai", model).inc(usage.prompt_tokens)
                ai_tokens_output_total.labels("openai", model).inc(usage.completion_tokens)
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                ai_requests_total.labels("openai", model, "refusal").inc()
                raise LLMRefusalError(message.refusal)
            if message.parsed is None:
                ai_requests_total.labels("openai", model, "failure").inc()
                raise LLMRefusalError("empty parsed structured output")
            ai_requests_total.labels("openai", model, "success").inc()
            return message.parsed
        except LLMRefusalError:
            raise
        except Exception:
            ai_requests_total.labels("openai", model, "failure").inc()
            raise

    async def run_tool_loop(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 700,
        temperature: float = 0.2,
        surface: str = "chat",
    ) -> LLMToolResponse:
        model = self.model_for_surface(surface)
        self.last_model = model
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else None,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = response.usage
            if usage:
                ai_tokens_input_total.labels("openai", model).inc(usage.prompt_tokens)
                ai_tokens_output_total.labels("openai", model).inc(usage.completion_tokens)
            ai_requests_total.labels("openai", model, "success").inc()
            msg = response.choices[0].message
            calls: list[LLMToolCall] = []
            for tc in msg.tool_calls or []:
                try:
                    parsed_args = _json.loads(tc.function.arguments or "{}")
                except _json.JSONDecodeError:
                    parsed_args = {}
                calls.append(LLMToolCall(id=tc.id, name=tc.function.name, arguments=parsed_args))
            return LLMToolResponse(content=msg.content, tool_calls=calls)
        except Exception:
            ai_requests_total.labels("openai", model, "failure").inc()
            raise


class MockChatClient:
    """Returns plausible responses for testing without an OpenAI API key."""

    model = "mock"
    last_model = "mock"

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
        surface: str = "general",
    ) -> str:
        prompt_lower = system_prompt.lower()

        if "irrigar" in prompt_lower or "irrigate" in prompt_lower:
            return (
                "Com base nos dados do sensor e nas condições meteorológicas actuais, "
                "a recomendação é regar este sector. O solo apresenta depleção acima do "
                "limiar permitido e não está prevista chuva nas próximas 48 horas. "
                "Se tiver o sistema de rega configurado, também poderei indicar o tempo "
                "de rega exacto."
            )

        if "resumo" in prompt_lower or "summary" in prompt_lower:
            return (
                "A exploração apresenta condições estáveis hoje. "
                "A maioria dos sectores não requer rega nas próximas 24 horas. "
                "Verifique os sectores com alertas activos para acção prioritária."
            )

        if "falta" in prompt_lower or "missing" in prompt_lower:
            return (
                "1. Qual é o tipo de solo predominante no seu talhão?\n"
                "2. Já instalou e configurou o sistema de rega neste sector?\n"
                "3. Em que fase fenológica se encontra a cultura actualmente?"
            )

        if "diagnostica" in prompt_lower or "diagnos" in prompt_lower:
            return (
                "• Uniformidade DU não configurada: sem DU definida, a dose calculada pode subestimar as perdas por distribuição desigual.\n"
                "• Evapotranspiração acima do esperado: com temperaturas acima de 30 °C e Kc de floração elevado, o consumo diário pode superar o limiar RAW em 2–3 dias.\n"
                "• Intervalo de rega longo: a última rega foi há mais de 4 dias — para este tipo de solo e fase, o ideal seria regas mais frequentes.\n"
                "• Configuração do sistema de rega em falta: sem taxa de aplicação definida, o motor usa padrão conservador que pode subestimar a dose necessária."
            )

        if "não enumeres padrões por profundidade" in prompt_lower:
            return _json.dumps(
                {
                    "summary": "Sonda mostra humidade estável e adequada.",
                    "risk_level": "low",
                    "irrigation_advice": (
                        "Não há necessidade de regar nos próximos 1-2 dias. "
                        "Monitoriza a tendência e rega se o consumo se tornar activo."
                    ),
                    "evidence": [
                        {"source": "depths[0].humidade_actual", "value": "humidade adequada"},
                        {"source": "depths[0].tendencia", "value": "estável"},
                    ],
                    "missing_data": [],
                    "confidence_score": 0.75,
                    "confidence_explanation": "Sinal estável com leituras suficientes nas últimas 72 horas.",
                    "recommended_actions": [
                        "Monitorizar a tendência de humidade nas próximas 24 horas.",
                    ],
                },
                ensure_ascii=False,
            )

        if (
            "interpreta" in prompt_lower
            or "sonda" in prompt_lower
            or "padrão" in prompt_lower
            or "flatline" in prompt_lower
        ):
            return (
                "• Sonda estável por solo saturado: variância < 0.001 m³/m³ com VWC próximo da CC → solo bem hidratado sem consumo radicular activo nem drenagem → normal após rega ou chuva abundante; reavaliar em 24-48h.\n"
                "• Absorção apenas nas raízes superficiais: depleção concentrada nos 30 cm, 60 cm estável → raízes activas predominantemente na camada rasa → confirmar se solo compactado impede penetração.\n"
                "• Rega atingiu 30 cm mas não 60 cm: +0.04 m³/m³ aos 30 cm, +0.002 m³/m³ aos 60 cm após rega → rega não atingiu a profundidade total → aumentar tempo de rega ou verificar DU."
            )

        if (
            "caudalímetro" in prompt_lower
            or "consumo de água" in prompt_lower
            or "flowmeter" in prompt_lower
        ):
            if "setor" in prompt_lower or "sector" in prompt_lower:
                return (
                    "O setor aplica em média 17.4 m³/ha por evento de rega, com intervalos regulares de 2-3 dias. "
                    "A consistência é alta — os volumes e intervalos variam pouco entre eventos. "
                    "O consumo está ligeiramente acima da média dos setores da mesma cultura."
                )
            return (
                "Nos últimos dias, a exploração aplicou um total significativo de água distribuído pelos setores ativos. "
                "O amendoal consome mais por setor do que o olival, em linha com as necessidades hídricas das culturas. "
                "Os setores com rega parada merecem verificação do estado do sistema. "
                "O padrão operacional é estável, com a maioria das regas a iniciar nas primeiras horas da manhã."
            )

        return (
            "Não tenho contexto suficiente para responder a essa pergunta. "
            "Por favor, forneça mais detalhes sobre o sector ou a questão."
        )

    async def complete_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema_model: type[BaseModel],
        *,
        max_tokens: int = 900,
        temperature: float = 0.1,
        surface: str = "structured",
    ) -> BaseModel:
        prompt_lower = system_prompt.lower()
        if "irrigar" in prompt_lower or "irrigate" in prompt_lower:
            risk, advice = "high", "Regar este setor — depleção acima do limiar."
        elif "skip" in prompt_lower or "defer" in prompt_lower or "não regar" in prompt_lower:
            risk, advice = "low", "Não regar — o balanço hídrico tem reserva suficiente."
        else:
            risk, advice = "medium", "Monitorizar a evolução do solo antes de alterar a rega."
        match = _re.search(r"\bev_[0-9a-f]{12}\b", system_prompt)
        common = {
            "summary": "Análise simulada do estado hídrico do setor.",
            "risk_level": risk,
            "irrigation_advice": advice,
            "missing_data": [],
            "confidence_score": 0.7,
            "confidence_explanation": "Resposta simulada para testes.",
            "recommended_actions": ["Validar com observação de campo."],
        }
        if schema_model is AgronomicInterpretation:
            evidence = [
                AgronomicEvidence(
                    evidence_id=match.group(0) if match else "",
                    source="water_balance.depletion_mm",
                    value="depleção dentro do esperado",
                    label="Água no solo",
                )
            ]
        else:
            evidence = [{"evidence_id": match.group(0)}] if match else []
        return schema_model.model_validate({**common, "evidence": evidence})

    async def run_tool_loop(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 700,
        temperature: float = 0.2,
        surface: str = "chat",
    ) -> LLMToolResponse:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = (m.get("content") or "").lower()
                break
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if tool_messages:
            try:
                last_tool_result = _json.loads(tool_messages[-1].get("content") or "{}")
            except _json.JSONDecodeError:
                last_tool_result = {}
            if "proposed_action" in last_tool_result:
                return LLMToolResponse(
                    content="Registei a proposta. Confirma na aplicação para a aplicar.",
                    tool_calls=[],
                )
            if "aceita" in last_user and last_tool_result.get("recommendation_id"):
                return LLMToolResponse(
                    content=None,
                    tool_calls=[
                        LLMToolCall(
                            id="mock-2",
                            name="propose_accept_recommendation",
                            arguments={"recommendation_id": last_tool_result["recommendation_id"]},
                        )
                    ],
                )
            return LLMToolResponse(
                content="Consultei os dados disponíveis para responder ao pedido.",
                tool_calls=[],
            )
        if "recalibr" in last_user or "calibra" in last_user:
            return LLMToolResponse(
                content=None,
                tool_calls=[LLMToolCall(id="mock-1", name="propose_run_calibration", arguments={})],
            )
        if "gerar" in last_user or "nova recomenda" in last_user or "regenera" in last_user:
            return LLMToolResponse(
                content=None,
                tool_calls=[
                    LLMToolCall(id="mock-1", name="propose_regenerate_recommendation", arguments={})
                ],
            )
        if "aceita" in last_user:
            return LLMToolResponse(
                content=None,
                tool_calls=[LLMToolCall(id="mock-1", name="get_sector_status", arguments={})],
            )
        if "substitu" in last_user or "override" in last_user or "regar" in last_user:
            m = _re.search(r"(\d+(?:\.\d+)?)\s*mm", last_user)
            depth = float(m.group(1)) if m else 10.0
            return LLMToolResponse(
                content=None,
                tool_calls=[
                    LLMToolCall(
                        id="mock-1",
                        name="propose_override",
                        arguments={
                            "recommendation_id": "rec-mock",
                            "depth_mm": depth,
                            "reason": "pedido do utilizador",
                        },
                    )
                ],
            )
        return LLMToolResponse(
            content=(
                "Com base nos dados disponíveis, o setor está estável e não "
                "requer rega imediata. Vigia a evolução nas próximas 24-48h."
            ),
            tool_calls=[],
        )


def get_chat_client(config: Settings) -> OpenAIChatClient | MockChatClient:
    if config.LLM_PROVIDER == "mock":
        return MockChatClient()
    if config.LLM_PROVIDER == "openai":
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return OpenAIChatClient(
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_MODEL,
            models={
                "chat": config.OPENAI_MODEL_CHAT or config.OPENAI_MODEL,
                "farm_summary": (
                    config.OPENAI_MODEL_SUMMARY
                    or config.OPENAI_MODEL_STRUCTURED
                    or config.OPENAI_MODEL
                ),
                "structured": config.OPENAI_MODEL_STRUCTURED or config.OPENAI_MODEL,
            },
            timeout_seconds=config.LLM_TIMEOUT_SECONDS,
            max_retries=config.LLM_MAX_RETRIES,
        )
    raise ValueError(f"Unknown LLM provider: {config.LLM_PROVIDER}")
