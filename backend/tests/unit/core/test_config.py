import pytest
from pydantic import ValidationError

from app.core.config import Settings

class TestSettings:
    def test_valid_settings(self):
        s = Settings(
            supabase_url="http://localhost",
            supabase_publishable_key="key",  
            supabase_secret_key="key",      
        )
        assert s.redis_host == "localhost"
        assert s.redis_port == 6379
        assert s.agent_status_ttl == 300
        assert s.debug is False
        assert s.llm.provider in ("openai", "ollama", "openrouter", "anthropic")
        assert s.embedding.model == "text-embedding-3-small"
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