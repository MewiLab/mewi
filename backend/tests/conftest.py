"""
Root conftest — shared fixtures for ALL tests.

Markers:
  - @pytest.mark.paid   → calls real APIs (OpenAI, Supabase). Excluded by default.
  - (no marker)         → unit tests using mocks. Always safe to run.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.config import Settings


# ── Fake Settings (no real credentials) ───────────────────────

@pytest.fixture
def settings():
    """Settings with dummy values — no .env file needed."""
    return Settings(
        supabase_url="http://fake-supabase.local",
        supabase_key="fake-key",
        openai_api_key="fake-openai-key",
        redis_host="localhost",
        redis_port=6379,
        agent_status_ttl=300,
    )


# ── Mock DB clients ──────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Async Redis mock — all methods return coroutines."""
    r = AsyncMock()
    r.get.return_value = None  # default: no key → idle
    return r


@pytest.fixture
def mock_supabase():
    """
    Supabase client mock with a chainable query builder.

    Usage in tests:
        mock_supabase.table("micrologs").insert(...).execute.return_value = ...
    """
    client = MagicMock()

    # Build a chainable query builder mock
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.update.return_value = builder
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.order.return_value = builder
    builder.range.return_value = builder
    builder.limit.return_value = builder
    builder.maybe_single.return_value = builder

    # Default execute returns empty data
    builder.execute.return_value = MagicMock(data=[])

    client.table.return_value = builder
    client._builder = builder  # expose for easy assertion in tests

    return client






"""
conftest.py — Shared fixtures for agent tests.

Every fixture builds from the bottom up:
  mock client → action manager → creature agent

No fixture requires a running Unity instance, real API keys, or network.
"""
from app.agent.schemas.perception import (
    Vector3,
    EntityObservation,
    CreatureSnapshot,
    EnvironmentSnapshot,
    PerceptionSummary,
    ThreatLevel,
)
from app.agent.schemas.action import ActionSchema
from app.agent.perception import SnapshotManager
from app.agent.memory import MemoryManager
from app.agent.action import ActionManager
from app.agent.agent import CreatureAgent

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