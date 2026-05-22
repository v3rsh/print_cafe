"""Typed application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "staging", "production"] = "local"
    app_debug: bool = False
    app_host: str = "0.0.0.0"  # noqa: S104
    app_port: int = 8000
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://printcafe:printcafe@postgres:5432/printcafe"

    redis_url: str = "redis://redis:6379/0"
    wazzup_incoming_stream: str = "wazzup:incoming"
    wazzup_incoming_group: str = "dialog_workers"
    wazzup_incoming_consumer: str = "worker-1"

    qdrant_url: str = "http://qdrant:6333"

    wazzup_api_key: SecretStr = SecretStr("")
    wazzup_api_base_url: str = "https://api.wazzup24.com"
    wazzup_webhook_secret: SecretStr = SecretStr("")
    wazzup_public_webhook_url: str = ""

    yandex_api_key: SecretStr = SecretStr("")
    yandex_folder_id: str = ""
    yandex_base_url: str = "https://llm.api.cloud.yandex.net/v1"
    yandex_model: str = "gpt://<folder_id>/yandexgpt/rc"
    yandex_temperature: float = 0.3
    yandex_max_tokens: int = 800
    yandex_data_logging_enabled: bool = False

    dialog_history_window: int = Field(default=20, ge=1, le=200)
    dialog_history_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=60)
    wazzup_dedup_ttl_seconds: int = Field(default=24 * 3600, ge=60)

    @field_validator("yandex_model")
    @classmethod
    def _check_yandex_model(cls, value: str) -> str:
        return value.strip()

    @property
    def yandex_model_resolved(self) -> str:
        if "<folder_id>" in self.yandex_model and self.yandex_folder_id:
            return self.yandex_model.replace("<folder_id>", self.yandex_folder_id)
        return self.yandex_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
