"""
config.py
---------
Central configuration via Pydantic Settings.
All values read from .env file or environment variables.
"""

from __future__ import annotations
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_name: str = "Autonomous Travel Agent API"
    debug: bool = False

    # Groq
    groq_api_key: str = ""

    # API Key Auth — stored as comma-separated string in .env
    api_keys: str = "dev-key-change-me-in-production"

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_api_keys(cls, v):
        return v  # keep as string; use .get_api_key_list() below

    def get_api_key_list(self) -> list[str]:
        """Return parsed list of valid API keys."""
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    # Rate limiting
    rate_limit_per_minute: int = 15

    # Cache
    cache_ttl_seconds: int = 300
    cache_max_size: int = 500

    # SQLite
    db_path: str = "travel_agent.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
