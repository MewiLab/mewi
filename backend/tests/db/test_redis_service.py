"""
Tests for AgentService — mocks async Redis so no real server is needed.

Replaces the old RedisService tests; status is now managed by
AgentService(redis, settings) with async set_status/get_status methods.
"""
from unittest.mock import AsyncMock
import pytest

from app.core.config import Settings
from app.services.agent import AgentService


@pytest.fixture
def settings():
    return Settings(
        supabase_url="http://fake",
        supabase_key="fake-key",
        openai_api_key="fake-openai-key",
    )


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get.return_value = None  # default: no key → idle
    return r


class TestAgentService:
    async def test_set_status_calls_redis_set_with_ttl(self, settings, mock_redis):
        svc = AgentService(mock_redis, settings)
        await svc.set_status("user-123", "thinking")
        mock_redis.set.assert_called_once_with(
            "agent_status:user-123", "thinking", ex=settings.agent_status_ttl
        )

    async def test_get_status_returns_stored_value(self, settings, mock_redis):
        mock_redis.get.return_value = "thinking"
        svc = AgentService(mock_redis, settings)
        result = await svc.get_status("user-123")
        assert result == "thinking"
        mock_redis.get.assert_called_once_with("agent_status:user-123")

    async def test_get_status_defaults_to_idle_when_key_missing(self, settings, mock_redis):
        mock_redis.get.return_value = None
        svc = AgentService(mock_redis, settings)
        result = await svc.get_status("user-456")
        assert result == "idle"

    async def test_ttl_comes_from_settings(self, mock_redis):
        custom_settings = Settings(
            supabase_url="http://fake",
            supabase_key="fake-key",
            openai_api_key="fake-openai-key",
            agent_status_ttl=999,
        )
        svc = AgentService(mock_redis, custom_settings)
        await svc.set_status("user-789", "idle")
        mock_redis.set.assert_called_once_with("agent_status:user-789", "idle", ex=999)
