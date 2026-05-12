"""
Unit tests for API routes.

Uses FastAPI's dependency override system to inject mocks.
No real Supabase, Redis, or OpenAI calls happen.
"""

from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.api.deps import get_supabase, get_redis, get_settings, get_agent, get_graph, get_agent_service


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


@pytest.fixture(autouse=True)
def reset_agent_service_singleton():
    import app.api.deps as deps_module
    deps_module._shared_state     = None
    deps_module._semantic_service = None
    yield
    deps_module._shared_state     = None
    deps_module._semantic_service = None


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


def _nested_unity_payload(i: int = 0) -> dict:
    """
    Build a single valid Unity nested-schema payload for HTTP tests.
    Matches TickPayload with alias="self" and alias="requestId".
    """
    return {
        "requestId": f"req-{i:03d}",
        "self": {
            "location":       {"x": float(i), "y": 0.0, "z": 0.0},
            "current_action": "walking",
        },
        "mood":   {"fear": 0.1, "trust": 0.8, "curiosity": 0.6, "social": 0.3, "energy": 0.9},
        "health": {"hunger": 0.2},
        "entities": [
            {"id": "lamp-01", "tags": ["lantern"], "distance": 3.0, "direction": "north"}
        ],
    }


class TestAgentRoutes:
    def test_get_status_returns_idle_by_default(self, client, mock_redis_dep):
        mock_redis_dep.get.return_value = None
        resp = client.get(f"/api/v1/agent/status/{FAKE_CREATURE_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["is_thinking"] is False

    def test_get_status_returns_thinking(self, client, mock_redis_dep):
        mock_redis_dep.get.return_value = b"thinking"
        resp = client.get(f"/api/v1/agent/status/{FAKE_CREATURE_ID}")
        data = resp.json()
        assert data["status"] == "thinking"
        assert data["is_thinking"] is True

    def test_get_status_response_contains_creature_id(self, client, mock_redis_dep):
        mock_redis_dep.get.return_value = None
        resp = client.get(f"/api/v1/agent/status/{FAKE_CREATURE_ID}")
        assert resp.json()["creature_id"] == FAKE_CREATURE_ID

    # ── Single-tick: new nested schema ────────────────────────────────────────

    def test_agent_tick_returns_200_with_action(
        self, client, mock_redis_dep, fake_settings, mock_db
    ):
        """
        POST /agent/tick/{creature_id} with the new nested Unity schema.
        creature_id is now a path parameter — not in the body.

        Uses aggregation_limit=1 so the very first tick is a flush tick and
        the LLM result is returned immediately (no buffering response).
        """
        from app.services.agent_service import AgentService

        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {
            "tick": 1,
            "action_result": {"success": True, "action": "move", "detail": "moving to target"},
            "reasoning": "I saw a mouse.",
        }
        mock_agent = MagicMock()
        mock_agent.memory.tick_count = 1
        mock_agent.body.available_actions = ["wait", "move"]

        def _single_tick_svc():
            return AgentService(
                redis=mock_redis_dep,
                settings=fake_settings,
                agent=mock_agent,
                graph=mock_graph,
                supabase=mock_db,
                aggregation_limit=1,
            )

        client.app.dependency_overrides[get_agent_service] = _single_tick_svc

        resp = client.post(
            f"/api/v1/agent/tick/{FAKE_CREATURE_ID}",
            json=_nested_unity_payload(0),
        )

        client.app.dependency_overrides.pop(get_agent_service, None)

        # Flush ticks now return 202 Accepted immediately; the LLM pipeline
        # runs in the background.  Unity polls GET /status for the result.
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "processing"

    def test_agent_tick_old_flat_url_returns_404(self, client):
        """The legacy endpoint /agent/tick (no creature_id) must no longer exist."""
        resp = client.post("/api/v1/agent/tick", json=_nested_unity_payload(0))
        assert resp.status_code == 404

    def test_agent_tick_invalid_body_returns_422(self, client):
        resp = client.post(
            f"/api/v1/agent/tick/{FAKE_CREATURE_ID}",
            headers={"Content-Type": "application/json"},
            content='"not a dict"',
        )
        assert resp.status_code == 422

    # ── Batch: 10 nested payloads ─────────────────────────────────────────────

    def test_agent_tick_batch_10_nested_payloads(self, client):
        """
        Send 10 consecutive Unity snapshots to the new endpoint.

        Assertions:
        - Every request returns HTTP 200.
        - The service received the creature_id as the first positional arg.
        - The service received the nested dict (with "self" and "requestId" keys).
        - Each call carried a distinct requestId so the service can track order.
        """
        mock_service = MagicMock()
        mock_service.run_full_tick_flow = AsyncMock(return_value={
            "tick":          1,
            "action_result": {"action": "wait"},
            "reasoning":     "buffering",
        })
        client.app.dependency_overrides[get_agent_service] = lambda: mock_service

        try:
            for i in range(10):
                resp = client.post(
                    f"/api/v1/agent/tick/{FAKE_CREATURE_ID}",
                    json=_nested_unity_payload(i),
                )
                assert resp.status_code == 200, (
                    f"tick {i} failed with {resp.status_code}: {resp.text}"
                )

            # Service was called exactly 10 times
            assert mock_service.run_full_tick_flow.call_count == 10

            # Verify every call was shaped correctly
            for idx, call in enumerate(mock_service.run_full_tick_flow.call_args_list):
                args, _ = call
                creature_id_arg, payload_arg, _bg = args

                # creature_id came from the URL path, not the body
                assert creature_id_arg == FAKE_CREATURE_ID

                # Payload uses the by_alias=True serialisation: "self", "requestId"
                assert "self"      in payload_arg, f"tick {idx}: 'self' key missing"
                assert "requestId" in payload_arg, f"tick {idx}: 'requestId' key missing"
                assert "mood"      in payload_arg, f"tick {idx}: 'mood' key missing"
                assert "health"    in payload_arg, f"tick {idx}: 'health' key missing"
                assert "entities"  in payload_arg, f"tick {idx}: 'entities' key missing"

                # Each tick carries its own requestId for ordering
                assert payload_arg["requestId"] == f"req-{idx:03d}"

        finally:
            client.app.dependency_overrides.pop(get_agent_service, None)


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
