import pytest
from pydantic import ValidationError

from app.core.config import Settings

class TestSettings:
    def test_valid_settings(self, monkeypatch):
        monkeypatch.delenv("REDIS_HOST", raising=False)
        s = Settings(
            supabase_url="http://localhost",
            supabase_publishable_key="key",
            supabase_secret_key="key",
            _env_file=None,
        )
        assert s.redis_host == "localhost"
        assert s.redis_port == 6379
        assert s.agent_status_ttl == 300
        assert s.debug is False
        assert s.llm.provider in ("openai", "ollama", "openrouter", "anthropic", "groq")
        assert s.embedding.model == "text-embedding-3-small"
        assert s.memory.graph_enabled is False
        assert s.memory.neo4j_username == "neo4j"
        assert s.log_level == "INFO"

    def test_missing_required_field_raises(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        with pytest.raises(ValidationError):
            Settings(
                supabase_publishable_key="key",
                supabase_secret_key="key",
                _env_file=None
            )

    def test_custom_redis_config(self):
        s = Settings(
            supabase_url="http://localhost",
            supabase_publishable_key="key",
            supabase_secret_key="key",
            redis_host="redis.internal",
            redis_port=6380,
        )
        assert s.redis_host == "redis.internal"
        assert s.redis_port == 6380

    def test_memory_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "true")
        monkeypatch.setenv("MEMORY_NEO4J_URL", "bolt://localhost:7687")
        monkeypatch.setenv("MEMORY_NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("MEMORY_NEO4J_PASSWORD", "secret")
        monkeypatch.setenv("MEMORY_PGVECTOR_DSN", "postgresql://example")

        s = Settings(
            supabase_url="http://localhost",
            supabase_publishable_key="key",
            supabase_secret_key="key",
            _env_file=None,
        )

        assert s.memory.graph_enabled is True
        assert s.memory.neo4j_url == "bolt://localhost:7687"
        assert s.memory.neo4j_password == "secret"
        assert s.memory.pgvector_dsn == "postgresql://example"
