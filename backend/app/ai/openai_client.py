"""OpenAI ChatGPT client for irrigation assistant.

Provides OpenAIChatClient (real API) and MockChatClient (testing without key).
Use get_chat_client(settings) to obtain the right instance.
"""

import openai

from app.config import Settings


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
        """Call OpenAI ChatGPT API. Low temperature for factual explanations."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


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
