"""
Integration test: verify Redis read/write with real server.

Marked @paid — requires a running Redis instance.
Only runs with `make test-integration CONFIRM_PAID=1`.

The `real_redis` fixture is provided by conftest.py (shared with E2E tests).
"""

import pytest

from app.services.agent import AgentService


@pytest.mark.paid
class TestRedisReal:
    async def test_set_and_get_status(self, real_settings, real_redis):
        svc = AgentService(real_redis, real_settings)
        await svc.set_status("test-integration-user", "thinking")
        result = await svc.get_status("test-integration-user")
        assert result == "thinking"

    async def test_missing_key_returns_idle(self, real_settings, real_redis):
        svc = AgentService(real_redis, real_settings)
        result = await svc.get_status("test-nonexistent-user-999")
        assert result == "idle"

    async def test_ttl_is_set(self, real_settings, real_redis):
        svc = AgentService(real_redis, real_settings)
        await svc.set_status("test-ttl-user", "thinking")
        ttl = await real_redis.ttl("agent_status:test-ttl-user")
        assert 0 < ttl <= real_settings.agent_status_ttl