from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"

LLMProviderName = Literal["openai", "anthropic", "ollama", "openrouter", "groq"]

_LLM_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "model": "gpt-4o-mini",
        "api_key": "",
        "base_url": "",
    },
    "anthropic": {
        "model": "claude-3-5-sonnet-latest",
        "api_key": "",
        "base_url": "",
    },
    "ollama": {
        "model": "llama3.1",
        "api_key": "ollama",
        "base_url": "http://localhost:11434/v1",
    },
    "openrouter": {
        "model": "openai/gpt-4o-mini",
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "groq": {
        "model": "llama-3.3-70b-versatile",
        "api_key": "",
        "base_url": "https://api.groq.com/openai/v1",
    },
}


class LLMSettings(BaseSettings):
    """
    Active LLM config.

    Switch providers with LLM_PROVIDER. Keep provider-specific values in
    LLM_OPENAI_*, LLM_OLLAMA_*, LLM_OPENROUTER_*, etc. The generic
    LLM_MODEL / LLM_API_KEY / LLM_BASE_URL remain as optional active-provider
    overrides, but provider-specific values win when present.
    """
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    provider: LLMProviderName = "openai"

    # Optional active-provider overrides.
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: float = 30.0

    # Provider-specific blocks. These let you switch only LLM_PROVIDER.
    openai_model: str = _LLM_DEFAULTS["openai"]["model"]
    openai_api_key: str = ""
    openai_base_url: str = ""

    anthropic_model: str = _LLM_DEFAULTS["anthropic"]["model"]
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""

    ollama_model: str = _LLM_DEFAULTS["ollama"]["model"]
    ollama_api_key: str = _LLM_DEFAULTS["ollama"]["api_key"]
    ollama_base_url: str = _LLM_DEFAULTS["ollama"]["base_url"]

    openrouter_model: str = _LLM_DEFAULTS["openrouter"]["model"]
    openrouter_api_key: str = ""
    openrouter_base_url: str = _LLM_DEFAULTS["openrouter"]["base_url"]

    groq_model: str = _LLM_DEFAULTS["groq"]["model"]
    groq_api_key: str = ""
    groq_base_url: str = _LLM_DEFAULTS["groq"]["base_url"]

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _resolve_active_provider(self):
        """Copy the selected provider block into model/api_key/base_url."""
        defaults = _LLM_DEFAULTS[self.provider]

        provider_model = getattr(self, f"{self.provider}_model", "")
        provider_api_key = getattr(self, f"{self.provider}_api_key", "")
        provider_base_url = getattr(self, f"{self.provider}_base_url", "")

        self.model = provider_model or self.model or defaults["model"]
        self.base_url = provider_base_url or self.base_url or defaults["base_url"]

        if self.provider == "ollama":
            self.api_key = provider_api_key or defaults["api_key"]
            self.base_url = self._normalize_ollama_base_url(self.base_url)
        else:
            self.api_key = provider_api_key or self.api_key or defaults["api_key"]

        return self

    @staticmethod
    def _normalize_ollama_base_url(base_url: str) -> str:
        base = (base_url or _LLM_DEFAULTS["ollama"]["base_url"]).rstrip("/")
        return base if base.endswith("/v1") else f"{base}/v1"


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    provider: Literal["openai", "openrouter", "custom"] = "openai"
    model:    str = "text-embedding-3-small"
    api_key:  str = ""        # falls back to OPENAI_API_KEY, then active LLM key
    base_url: str = ""        # leave empty for OpenAI default


class LangSmithSettings(BaseSettings):
    """
    LangSmith tracing config. When `tracing` is true, the lifespan exports
    LANGSMITH_* env vars so LangChain/LangGraph auto-instrumentation picks them up.
    """
    model_config = SettingsConfigDict(
        env_prefix="LANGSMITH_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    tracing:  bool = False
    api_key:  str = ""
    project:  str = "cat-brain"
    endpoint: str = "https://api.smith.langchain.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
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
    place_memory_ttl_seconds: int = 604_800
    place_memory_refresh_seconds: float = 30.0
    log_level: str = "INFO"
    log_file_path: str | None = None  # Opt in locally via LOG_FILE_PATH=app.log in .env
    log_max_bytes: int = 5_000_000         # 5 MB
    log_backup_count: int = 3
    cat_journal_dir: str = "app/cat_journal/journal"
    
    # Legacy compatibility; prefer LLM_OLLAMA_BASE_URL now.
    ollama_base_url: str = ""

    # OpenAI API key fallback for services that need a real embedding key
    openai_api_key: str = ""

    # Nested LLM Config
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    langsmith: LangSmithSettings = Field(default_factory=LangSmithSettings)
    
    # Auth
    API_SECRET_TOKEN: str = "dev-secret-change-me"

    # Feature toggles
    ENABLE_MEMORY_PIPELINE: bool = False    # Redis buffer → embedding → perception_snapshots
    ENABLE_REFLECTION_CYCLE: bool = False   # LLM reflection → memory_summaries
    BUFFER_FLUSH_THRESHOLD: int = 10        # items in Redis LIST before a count-trigger flush

    # Workers
    agent_worker_interval: float = 10.0       # seconds between agent ticks
    microlog_worker_interval: float = 30.0    # seconds between embedding batches

    # Agent prompts
    agent_persona: str = "mewi"
    agent_personas: str = "default:mewi,mewi:mewi,miso:miso,pixie:pixie,haru:haru,ratz:ratz,mao:mao,lioner:lioner,feifei:feifei,yuzu:yuzu,sasha:sasha,slime:slime,kosto:kosto,shoma:shoma,yeti:yeti,yuna:yuna,gugu:gugu"

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value

    @model_validator(mode="after")
    def _apply_cross_setting_fallbacks(self):
        if self.llm.provider == "openai" and not self.llm.api_key:
            self.llm.api_key = self.openai_api_key
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only read once per process."""
    return Settings()
