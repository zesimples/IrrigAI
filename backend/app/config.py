from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://irrigai:irrigai_dev@db:5432/irrigai"
    DATABASE_URL_SYNC: str = "postgresql://irrigai:irrigai_dev@db:5432/irrigai"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Backend
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = ""  # For DB field encryption; derived from SECRET_KEY if blank
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Data providers
    PROBE_PROVIDER: Literal["mock", "irriwatch", "myirrigation"] = "mock"
    PROBE_API_URL: str = ""
    PROBE_API_KEY: str = ""

    WEATHER_PROVIDER: Literal["mock", "irriwatch", "myirrigation"] = "mock"
    WEATHER_API_URL: str = ""
    WEATHER_API_KEY: str = ""

    # IrriWatch (Hydrosat) — used when PROBE_PROVIDER=irriwatch or WEATHER_PROVIDER=irriwatch
    IRRIWATCH_BASE_URL: str = "https://api.irriwatch.hydrosat.com"
    IRRIWATCH_CLIENT_ID: str = ""      # API Key shown in IrriWatch portal
    IRRIWATCH_CLIENT_SECRET: str = ""  # Password shown in IrriWatch portal
    IRRIWATCH_COMPANY_UUID: str = ""   # Company UUID (see /api/v1/company after login)

    # MyIrrigation — used when PROBE_PROVIDER=myirrigation or WEATHER_PROVIDER=myirrigation
    MYIRRIGATION_BASE_URL: str = "https://api.myirrigation.eu/api/v1"
    MYIRRIGATION_USERNAME: str = ""
    MYIRRIGATION_PASSWORD: str = ""
    MYIRRIGATION_CLIENT_ID: str = ""
    MYIRRIGATION_CLIENT_SECRET: str = ""
    MYIRRIGATION_PROJECT_ID: str = ""     # for weather forecast endpoints; auto-detected if blank
    MYIRRIGATION_WEATHER_DEVICE_ID: str = ""  # iMetos station device ID for observations/ET0

    # LLM — OpenAI ChatGPT
    LLM_PROVIDER: Literal["openai", "mock"] = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Observability
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "production"

    # Localization
    DEFAULT_LANGUAGE: str = "pt"
    DEFAULT_TIMEZONE: str = "Europe/Lisbon"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


_INSECURE_SECRET_KEY = "change-me-in-production"


def check_production_security(settings: Settings) -> None:
    """Fail fast on insecure key configuration when running outside DEBUG.

    Called at application startup. In production a dedicated ENCRYPTION_KEY is
    mandatory — otherwise field encryption silently derives its key from
    SECRET_KEY, so one leaked JWT secret also exposes every encrypted farm
    credential. The placeholder SECRET_KEY is likewise rejected.
    """
    if settings.DEBUG:
        return
    problems: list[str] = []
    if not settings.ENCRYPTION_KEY:
        problems.append(
            "ENCRYPTION_KEY is not set — refusing to derive the field-encryption "
            "key from SECRET_KEY in production. Generate a dedicated key and set "
            "ENCRYPTION_KEY."
        )
    if settings.SECRET_KEY == _INSECURE_SECRET_KEY:
        problems.append(
            "SECRET_KEY is still the placeholder default — set a unique secret."
        )
    if problems:
        raise RuntimeError(
            "Insecure production configuration (set DEBUG=true only for local/dev):\n- "
            + "\n- ".join(problems)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
