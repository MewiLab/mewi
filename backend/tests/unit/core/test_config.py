"""
Unit tests for core/config.py — Settings validation.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestSettings:
    def test_valid_settings(self):
        s = Settings(
            supabase_url="http://localhost",
            supabase_key="key",
            openai_api_key="sk-test",
        )
        assert s.redis_host == "localhost"
        assert s.redis_port == 6379
        assert s.agent_status_ttl == 300
        assert s.debug is False

    def test_missing_required_field_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            # _env_file=None prevents pydantic-settings from reading .env
            Settings(supabase_url="http://localhost", supabase_key="key", _env_file=None)
            # missing openai_api_key

    def test_custom_redis_config(self):
        s = Settings(
            supabase_url="http://localhost",
            supabase_key="key",
            openai_api_key="sk-test",
            redis_host="redis.internal",
            redis_port=6380,
        )
        assert s.redis_host == "redis.internal"
        assert s.redis_port == 6380
