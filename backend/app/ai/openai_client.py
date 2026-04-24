"""OpenAI ChatGPT client for irrigation assistant.

Provides OpenAIChatClient (real API) and MockChatClient (testing without key).
Use get_chat_client(settings) to obtain the right instance.
"""

import logging

import openai

from app.config import Settings
from app.metrics import ai_requests_total, ai_tokens_input_total, ai_tokens_output_total

logger = logging.getLogger(__name__)


class OpenAIChatClient:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = response.usage
            if usage:
                ai_tokens_input_total.labels("openai", self.model).inc(usage.prompt_tokens)
                ai_tokens_output_total.labels("openai", self.model).inc(usage.completion_tokens)
                logger.debug(
                    "openai_usage",
                    extra={"model": self.model, "prompt_tokens": usage.prompt_tokens,
                           "completion_tokens": usage.completion_tokens},
                )
            ai_requests_total.labels("openai", self.model, "success").inc()
            return response.choices[0].message.content or ""
        except Exception:
            ai_requests_total.labels("openai", self.model, "failure").inc()
            raise


class MockChatClient:
    """Returns plausible responses for testing without an OpenAI API key."""

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
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

        if "interpreta" in prompt_lower or "sonda" in prompt_lower or "padrão" in prompt_lower or "flatline" in prompt_lower:
            return (
                "• Sonda estável por solo saturado: variância < 0.001 m³/m³ com VWC próximo da CC → solo bem hidratado sem consumo radicular activo nem drenagem → normal após rega ou chuva abundante; reavaliar em 24-48h.\n"
                "• Absorção apenas nas raízes superficiais: depleção concentrada nos 30 cm, 60 cm estável → raízes activas predominantemente na camada rasa → confirmar se solo compactado impede penetração.\n"
                "• Rega atingiu 30 cm mas não 60 cm: +0.04 m³/m³ aos 30 cm, +0.002 m³/m³ aos 60 cm após rega → rega não atingiu a profundidade total → aumentar tempo de rega ou verificar DU."
            )

        return (
            "Não tenho contexto suficiente para responder a essa pergunta. "
            "Por favor, forneça mais detalhes sobre o sector ou a questão."
        )


def get_chat_client(config: Settings) -> OpenAIChatClient | MockChatClient:
    if config.LLM_PROVIDER == "mock":
        return MockChatClient()
    if config.LLM_PROVIDER == "openai":
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return OpenAIChatClient(api_key=config.OPENAI_API_KEY, model=config.OPENAI_MODEL)
    raise ValueError(f"Unknown LLM provider: {config.LLM_PROVIDER}")
