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
    MYIRRIGATION_BASE_URL: str = "http://api.myirrigation.eu/api/v1"
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

    # Localization
    DEFAULT_LANGUAGE: str = "pt"
    DEFAULT_TIMEZONE: str = "Europe/Lisbon"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
