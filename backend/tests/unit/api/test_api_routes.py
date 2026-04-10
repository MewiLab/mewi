"""
Unit tests for API routes.

Uses FastAPI's dependency override system to inject mocks.
No real Supabase, Redis, or OpenAI calls happen.
"""

from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch
from app.api.deps import get_graph

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.api.deps import get_supabase, get_redis, get_settings, get_agent


FAKE_USER_ID = str(uuid4())
FAKE_LOG_ID = str(uuid4())

FAKE_ROW = {
    "id": FAKE_LOG_ID,
    "user_id": FAKE_USER_ID,
    "content": "今天看到流浪貓",
    "valence": 0.5,
    "arousal": 0.2,
    "image_url": None,
    "video_url": None,
    "voice_url": None,
    "created_at": "2025-06-01T12:00:00Z",
}


@pytest.fixture
def mock_db():
    """Chainable Supabase mock."""
    client = MagicMock()
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.update.return_value = builder
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.order.return_value = builder
    builder.range.return_value = builder
    builder.limit.return_value = builder
    builder.execute.return_value = MagicMock(data=[FAKE_ROW])
    client.table.return_value = builder
    return client


@pytest.fixture
def mock_redis_dep():
    from unittest.mock import AsyncMock
    return AsyncMock()


@pytest.fixture
def client(fake_settings, mock_db, mock_redis_dep):
    """FastAPI TestClient with all external deps overridden."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis_dep
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ── /health ───────────────────────────────────────────────────

class TestHealthCheck:
    def test_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── /api/v1/micrologs ────────────────────────────────────────

class TestMicrologRoutes:
    def test_get_logs_returns_list(self, client):
        resp = client.get(f"/api/v1/micrologs/{FAKE_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_logs_with_count_param(self, client):
        resp = client.get(f"/api/v1/micrologs/{FAKE_USER_ID}?count=5&offset=0")
        assert resp.status_code == 200

    def test_get_logs_invalid_uuid_returns_422(self, client):
        resp = client.get("/api/v1/micrologs/not-a-uuid")
        assert resp.status_code == 422

    @patch("app.services.embedding_service.EmbeddingService.embed_text", return_value=[0.1] * 1536)
    def test_create_log_returns_201(self, mock_embed, client):
        payload = {
            "user_id": FAKE_USER_ID,
            "content": "今天天氣真好",
            "valence": 0.8,
            "arousal": 0.3,
        }
        resp = client.post("/api/v1/micrologs/", json=payload)
        assert resp.status_code == 201
        assert resp.json()["content"] == "今天看到流浪貓"  # from mock

    def test_create_log_missing_content_returns_422(self, client):
        payload = {"user_id": FAKE_USER_ID}
        resp = client.post("/api/v1/micrologs/", json=payload)
        assert resp.status_code == 422


# ── /api/v1/agent ─────────────────────────────────────────────

FAKE_CREATURE_ID = str(uuid4())
FAKE_SNAPSHOT = {"location": "park", "mood": "curious", "nearby_humans": 2}


class TestAgentRoutes:
    def test_get_status_returns_idle_by_default(self, client, mock_redis_dep):
        mock_redis_dep.get.return_value = None
        resp = client.get(f"/api/v1/agent/status/{FAKE_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["is_thinking"] is False

    def test_get_status_returns_thinking(self, client, mock_redis_dep):
        mock_redis_dep.get.return_value = b"thinking"
        resp = client.get(f"/api/v1/agent/status/{FAKE_USER_ID}")
        data = resp.json()
        assert data["status"] == "thinking"
        assert data["is_thinking"] is True

    def test_agent_tick_returns_200_with_action(self, client):
        # 1. Create a mock graph object with our fake ainvoke response
        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {
            "tick": 1,
            "action_result": {"success": True, "action": "move", "detail": "moving to target"},
            "reasoning": "I saw a mouse.",
        }

        # Mock the agent with tick_count > 0 so _hydrate_if_empty is skipped.
        # Without this, the real agent (tick_count=0) would trigger hydrate_agent,
        # which would call mock_db on agent_tick_history and hit a KeyError since
        # mock_db returns FAKE_ROW (a microlog row without a "perception" key).
        mock_agent = MagicMock()
        mock_agent.memory.tick_count = 1
        mock_agent.body.available_actions = ["wait", "move"]

        # 2. Tell FastAPI to use our mock graph / agent instead of the real ones
        client.app.dependency_overrides[get_graph] = lambda: mock_graph
        client.app.dependency_overrides[get_agent] = lambda: mock_agent

        # 3. Send the payload
        payload = {
            "environment_snapshot": {},
            "creature_snapshot": {}
        }
        resp = client.post("/api/v1/agent/tick", json=payload)

        # 4. Clean up the overrides so they don't affect other tests
        client.app.dependency_overrides.pop(get_graph, None)
        client.app.dependency_overrides.pop(get_agent, None)

        # 5. Assert the response
        assert resp.status_code == 200
        data = resp.json()
        assert data["tick"] == 1
        assert data["action"]["action"] == "move"
        assert data["reasoning"] == "I saw a mouse."

    def test_agent_tick_invalid_payload_returns_422(self, client):
        # Sending a string instead of a JSON dictionary to trigger Pydantic validation
        resp = client.post(
            "/api/v1/agent/tick", 
            headers={"Content-Type": "application/json"},
            content='"not a dictionary"'
        )
        assert resp.status_code == 422


# ── /api/v1/assets ────────────────────────────────────────────

class TestAssetRoutes:
    @patch("app.services.storage_service.StorageService.upload", return_value="https://cdn.example.com/cat.png")
    def test_upload_returns_url(self, mock_upload, client):
        resp = client.post(
            "/api/v1/assets/upload",
            data={"user_id": "user-1", "media_type": "image"},
            files={"file": ("cat.png", b"fake-bytes", "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://cdn.example.com/cat.png"

    def test_upload_invalid_media_type_returns_422(self, client):
        resp = client.post(
            "/api/v1/assets/upload",
            data={"user_id": "user-1", "media_type": "invalid"},
            files={"file": ("cat.png", b"fake", "image/png")},
        )
        assert resp.status_code == 422
