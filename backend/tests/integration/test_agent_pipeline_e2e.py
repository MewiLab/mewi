"""
Integration test: full agent pipeline E2E via TestClient.

Uses FastAPI's TestClient — calls the app in-process, no running server needed.
Real Supabase + Redis are used (injected via dependency overrides in conftest).

Marked @paid — calls real Supabase, Redis, and OpenAI.
Only runs with `make test-integration CONFIRM_PAID=1`.
"""

import time

import pytest

TEST_USER_ID = "66af1b4c-4628-4544-addd-15c9a36b4707"


@pytest.mark.paid
@pytest.mark.asyncio
class TestAgentPipelineE2E:

    async def test_health(self, real_client):
        resp = await real_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_initial_status_is_idle(self, real_client):
        resp = await real_client.get(f"/api/v1/agent/status/{TEST_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["is_thinking"] is False

    async def test_create_microlog_returns_201(self, real_client, test_user):
        """POST a microlog — verify it persists and returns the created row."""
        payload = {
            "user_id": TEST_USER_ID,
            "content": "Integration test: verify full pipeline",
            "valence": 0.9,
            "arousal": 0.5,
        }
        resp = await real_client.post("/api/v1/micrologs/", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == TEST_USER_ID
        assert data["content"] == payload["content"]
        assert data["id"] is not None

    async def test_get_logs_returns_recent_entry(self, real_client, test_user):
        """After creating a log, GET should return it."""
        # Create one first
        await real_client.post("/api/v1/micrologs/", json={
            "user_id": TEST_USER_ID,
            "content": "Entry for GET test",
            "valence": 0.5,
            "arousal": 0.3,
        })

        resp = await real_client.get(f"/api/v1/micrologs/{TEST_USER_ID}?count=1")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["user_id"] == TEST_USER_ID