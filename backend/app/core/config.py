from functools import lru_cache
from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class LLMSettings(BaseSettings):
    """
    All LLM config in one place. Switch provider with a single env var.
    Examples (.env):
        LLM_PROVIDER=openai
        LLM_PROVIDER=ollama        LLM_BASE_URL=http://localhost:11434
        LLM_PROVIDER=openrouter    LLM_API_KEY=sk-or-...  LLM_MODEL=anthropic/claude-sonnet-4-5
    """
    model_config = SettingsConfigDict(
        env_prefix="LLM_", 
        env_file=".env", 
        extra="ignore"
    )

    provider: Literal["openai", "anthropic", "ollama", "openrouter", "groq"] = "openai"
    model: str = "gpt-4-turbo"  # Updated to a valid default model
    api_key: str = ""
    base_url: str = ""          # Override via LLM_BASE_URL in .env
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: float = 30.0

    @model_validator(mode="after")
    def _set_defaults(self):
        """Fill in sensible base_url defaults so callers never have to."""
        if self.provider == "ollama" and not self.base_url:
            self.base_url = "http://localhost:11434/v1"
        if self.provider == "openrouter" and not self.base_url:
            self.base_url = "https://openrouter.ai/api/v1"
        if self.provider == "groq" and not self.base_url:
            self.base_url = "https://api.groq.com/openai/v1"
        return self


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_", 
        env_file=".env", 
        extra="ignore"
    )

    model:    str = "text-embedding-3-small"
    api_key:  str = ""        # falls back to LLM_API_KEY if empty
    base_url: str = ""        # leave empty for OpenAI default


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    env: str = "production"

    # Supabase
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    supabase_timeout: float = 10.0
    
    # Redis
    redis_url: str | None = None

    # origin Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # System
    debug: bool = False
    agent_status_ttl: int = 300  
    log_level: str = "INFO"
    log_file_path: str | None = None  # Opt in locally via LOG_FILE_PATH=app.log in .env
    log_max_bytes: int = 5_000_000         # 5 MB
    log_backup_count: int = 3
    
    # Ollama
    ollama_base_url: str = ""

    # OpenAI API key fallback for services that need a real embedding key
    openai_api_key: str = ""

    # unity
    unity_bridge_url: str = "http://localhost:8080"
    unity_transport: Literal["http", "proxy"] = "http"
    
    # Nested LLM Config
    llm: LLMSettings = LLMSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    
    # Workers
    agent_worker_interval: float = 10.0       # seconds between agent ticks
    microlog_worker_interval: float = 30.0    # seconds between embedding batches


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only read once per process."""
    return Settings()