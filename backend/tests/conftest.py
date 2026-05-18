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


# ── Integration fixtures (real connections, require .env) ─────────────────────

@pytest.fixture
def real_settings():
    """Load real settings from .env — all env vars must be set."""
    return Settings()


@pytest.fixture
async def real_redis(real_settings):
    """Create a real async Redis connection."""
    from app.core.redis import create_redis, close_redis
    redis = create_redis(real_settings)
    yield redis
    await close_redis(redis)


@pytest.fixture
def real_supabase(real_settings):
    """Create a real Supabase client using the service role key."""
    return create_supabase(real_settings)


@pytest.fixture
def test_user(real_supabase):
    """Ensure TEST_USER_ID exists in the users table (FK guard for micrologs).

    Upserts before the test, deletes after — keeps Supabase clean.
    """
    user_id = "66af1b4c-4628-4544-addd-15c9a36b4707"
    real_supabase.table("users").upsert({"id": user_id}).execute()
    yield user_id
    real_supabase.table("micrologs").delete().eq("user_id", user_id).execute()
    real_supabase.table("users").delete().eq("id", user_id).execute()


@pytest.fixture
async def real_client(real_settings, real_redis, real_supabase):
    """httpx AsyncClient wired to a fresh FastAPI app with real dependencies.

    Uses dependency_overrides so the lifespan (which needs Unity/OpenAI)
    never runs — only the route-layer deps are replaced.
    """
    from app.main import create_app
    from app.api.deps import get_settings, get_redis, get_supabase

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: real_settings
    app.dependency_overrides[get_redis] = lambda: real_redis
    app.dependency_overrides[get_supabase] = lambda: real_supabase

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": real_settings.API_SECRET_TOKEN},
    ) as client:
        yield client

    app.dependency_overrides.clear()


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



"""
Test for agent grpah

Every fixture builds from the bottom up:
  mock client → action manager → creature agent
"""
from app.agent.schemas.perception_schema import (
    Vector3,
    EntityObservation,
    CreatureSnapshot,
    EnvironmentSnapshot,
    PerceptionSummary,
    ThreatLevel,
)
from app.agent.schemas.action_schema import ActionSchema
from app.agent.perception import SnapshotManager
from app.agent.memory import MemoryManager
from app.agent.action import ActionManager
from app.agent.creature_agent import CreatureAgent

from tests.mock_unity_client import MockUnityClient


# ─── Unity client ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_client() -> MockUnityClient:
    """A fresh mock client with default actions registered."""
    client = MockUnityClient()
    client.add_action("Sprint", "toggle", "Hold to run faster")
    client.add_action("Jump", "press", "Jump or climb surface")
    client.add_action("Attack1", "press", "Primary attack")
    return client


# ─── Subsystems ──────────────────────────────────────────────────────────────

@pytest.fixture
def eye() -> SnapshotManager:
    return SnapshotManager(relevance_radius=30.0, threat_radius=10.0)


@pytest.fixture
def memory() -> MemoryManager:
    return MemoryManager(max_ticks=20)


@pytest.fixture
def body(mock_client) -> ActionManager:
    return ActionManager(client=mock_client)


# ─── Agent ───────────────────────────────────────────────────────────────────

@pytest.fixture
def agent(eye, memory, body) -> CreatureAgent:
    return CreatureAgent(eye=eye, memory=memory, body=body)


# ─── Sample data builders ───────────────────────────────────────────────────

@pytest.fixture
def make_unity_payload():
    """Factory fixture — call with overrides to build a Unity JSON payload."""

    def _build(
        creature_pos: tuple[float, float, float] = (10, 0, 5),
        creature_state: str = "Locomotion",
        entities: list[dict] | None = None,
        time_of_day: float = 12.0,
    ) -> dict:
        if entities is None:
            entities = []

        return {
            "environment_snapshot": {
                "time_of_day": time_of_day,
                "weather": "clear",
                "entities": entities,
            },
            "creature_snapshot": {
                "position": {"x": creature_pos[0], "y": creature_pos[1], "z": creature_pos[2]},
                "rotation_y": 0.0,
                "active_state": creature_state,
                "active_stance": "Default",
                "grounded": True,
                "speed": 1.0,
                "sprint": False,
            },
        }

    return _build


@pytest.fixture
def make_entity():
    """Factory fixture — build an entity dict for inclusion in payloads."""

    def _build(
        name: str = "Dog",
        tag: str = "neutral",
        pos: tuple[float, float, float] = (15, 0, 5),
    ) -> dict:
        return {
            "name": name,
            "tag": tag,
            "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
            "distance": 0.0,
        }

    return _build