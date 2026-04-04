"""
Centralised configuration via Pydantic Settings.

Every service reads from here — no more scattered os.getenv() calls.
Add new env vars here; they are validated at import time.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Supabase ──────────────────────────────────────────────
    supabase_url: str
    supabase_key: str
    supabase_timeout: float = 10.0  # seconds
    
    # ── Redis ─────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # ── OpenAI ────────────────────────────────────────────────
    openai_api_key: str

    # ── App ───────────────────────────────────────────────────
    debug: bool = False
    agent_status_ttl: int = 300  # seconds
    
    # ── App ───────────────────────────────────────────────────
    unity_bridge_url: str = "http://localhost:8080"
    


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only read once per process."""
    return Settings()