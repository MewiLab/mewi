"""
Unit tests for AgentService.

Async Redis is fully mocked — no real Redis server needed.
"""

import pytest

from app.services.agent import AgentService


class TestSetStatus:
    async def test_writes_key_with_ttl(self, settings, mock_redis):
        svc = AgentService(mock_redis, settings)
        await svc.set_status("user-123", "thinking")
        mock_redis.set.assert_called_once_with(
            "agent_status:user-123", "thinking", ex=settings.agent_status_ttl,
        )

    async def test_custom_ttl_from_settings(self, mock_redis):
        from app.core.config import Settings

        custom = Settings(
            supabase_url="http://fake",
            supabase_key="k",
            openai_api_key="k",
            agent_status_ttl=999,
        )
        svc = AgentService(mock_redis, custom)
        await svc.set_status("user-1", "idle")
        mock_redis.set.assert_called_once_with("agent_status:user-1", "idle", ex=999)


class TestGetStatus:
    async def test_returns_stored_value(self, settings, mock_redis):
        mock_redis.get.return_value = "thinking"
        svc = AgentService(mock_redis, settings)
        assert await svc.get_status("user-123") == "thinking"
        mock_redis.get.assert_called_once_with("agent_status:user-123")

    async def test_defaults_to_idle_when_key_missing(self, settings, mock_redis):
        mock_redis.get.return_value = None
        svc = AgentService(mock_redis, settings)
        assert await svc.get_status("user-456") == "idle"
