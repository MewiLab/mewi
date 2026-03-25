"""
Shared test fixtures.

- Unit fixtures (settings, mock_redis, mock_supabase): no real connections.
- Integration fixtures (real_*): loads real credentials from .env.
  Only used when running `make test-integration CONFIRM_PAID=1`.
"""

import os
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

import pytest
import redis.asyncio as aioredis
from dotenv import load_dotenv

from app.core.config import Settings
from app.api.deps import get_supabase, get_redis, get_settings
from app.core.supabase import create_supabase
from app.main import create_app

load_dotenv(override=True)  # .env values win over pytest-env fakes


# ── Unit fixtures (no real connections) ───────────────────────────────────────

@pytest.fixture
def mock_settings():
    return Settings(
        supabase_url="http://fake-supabase",
        supabase_publishable_key="fake-anon-key",
        supabase_secret_key="fake-secret-key",
        openai_api_key="fake-openai-key"
    )


@pytest.fixture
def settings(mock_settings):
    return mock_settings


@pytest.fixture
def fake_settings(mock_settings):
    return mock_settings


@pytest.fixture
def mock_redis():
    client = AsyncMock()
    client.set = AsyncMock()
    client.get = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_supabase():
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.update.return_value = builder
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.order.return_value = builder
    builder.limit.return_value = builder
    builder.range.return_value = builder
    builder.single.return_value = builder
    builder.maybe_single.return_value = builder
    builder.execute.return_value = MagicMock(data=[])

    client = MagicMock()
    client.table.return_value = builder
    client._builder = builder
    return client


# ── Integration fixtures (real credentials from .env) ─────────────────────────

@pytest.fixture
def real_settings():
    """Settings from your actual .env file."""
    return Settings(
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_publishable_key=os.environ["SUPABASE_PUBLISHABLE_KEY"],
        supabase_secret_key=os.environ["SUPABASE_SECRET_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", 6379)),
    )


@pytest.fixture
def real_supabase(real_settings):
    """Real Supabase client from factory."""
    return create_supabase(real_settings)


@pytest.fixture
async def real_redis(real_settings):
    """Real async Redis client. Cleans up test keys after use."""
    pool = aioredis.ConnectionPool.from_url(
        f"redis://{real_settings.redis_host}:{real_settings.redis_port}/0",
        decode_responses=True,
    )
    client = aioredis.Redis(connection_pool=pool)
    yield client
    # Cleanup test keys
    keys = await client.keys("agent_status:test-*")
    if keys:
        await client.delete(*keys)
    await client.aclose()
    await pool.disconnect()


@pytest.fixture
async def real_client(real_settings, real_supabase, real_redis):
    """
    Truly ASYNC test client wired to REAL Supabase + Redis.

    We use httpx.AsyncClient + ASGITransport instead of FastAPI's TestClient
    so that the tests, the app, and the database connections all happily 
    share the exact same asyncio event loop.
    """
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: real_settings
    app.dependency_overrides[get_supabase] = lambda: real_supabase
    app.dependency_overrides[get_redis] = lambda: real_redis

    # 1. Wrap your FastAPI app in an ASGI transport layer
    transport = ASGITransport(app=app)
    
    # 2. Use httpx.AsyncClient instead of TestClient
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
