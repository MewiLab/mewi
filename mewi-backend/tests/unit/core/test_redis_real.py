"""
Integration test: verify Redis read/write with real server.

Marked @paid — requires a running Redis instance.
Only runs with `make test-all CONFIRM_PAID=1`.
"""

import pytest
import redis.asyncio as aioredis

from app.services.agent_service import AgentService


@pytest.fixture
async def real_redis(real_settings):
    """Connect to real Redis, yield client, then clean up test keys."""
    pool = aioredis.ConnectionPool.from_url(
        f"redis://{real_settings.redis_host}:{real_settings.redis_port}/0",
        decode_responses=True,
    )
    client = aioredis.Redis(connection_pool=pool)
    yield client
    # Cleanup: delete any test keys we created
    keys = await client.keys("agent_status:test-*")
    if keys:
        await client.delete(*keys)
    await client.aclose()
    await pool.disconnect()


@pytest.mark.paid
class TestRedisReal:
    async def test_set_and_get_status(self, real_settings, real_redis):
        svc = AgentService(real_redis, real_settings)
        await svc._set_status("test-integration-user", "thinking")
        result = await svc.get_status("test-integration-user")
        assert result == "thinking"

    async def test_missing_key_returns_idle(self, real_settings, real_redis):
        svc = AgentService(real_redis, real_settings)
        result = await svc.get_status("test-nonexistent-user-999")
        assert result == "idle"

    async def test_ttl_is_set(self, real_settings, real_redis):
        svc = AgentService(real_redis, real_settings)
        await svc._set_status("test-ttl-user", "thinking")
        ttl = await real_redis.ttl("agent_status:test-ttl-user")
        assert 0 < ttl <= real_settings.agent_status_ttl
