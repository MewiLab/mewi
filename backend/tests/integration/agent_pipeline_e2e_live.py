"""
Integration test: full agent pipeline E2E.

Replaces the old upload.py script.
Posts a microlog → polls agent status → verifies the thinking→idle cycle.

Marked @paid — calls real Supabase, Redis, and OpenAI.
Only runs with `make test-all CONFIRM_PAID=1`.

Usage:
    CONFIRM_PAID=1 make test-all -k test_agent_pipeline
"""

import os
import time

import pytest
import requests

BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000/api/v1")
TEST_USER_ID = os.getenv(
    "TEST_USER_ID", "66af1b4c-4628-4544-addd-15c9a36b4707"
)


def _api(method: str, path: str, **kwargs):
    """Helper: call the running API and return parsed JSON."""
    resp = getattr(requests, method)(f"{BASE_URL}{path}", **kwargs)
    resp.raise_for_status()
    return resp.json()


@pytest.mark.paid
class TestAgentPipelineE2E:
    """
    Requires a running server:
        docker compose up -d
        CONFIRM_PAID=1 make test-all -k test_agent_pipeline
    """

    def test_health(self):
        data = _api("get", "/../health")
        assert data["status"] == "ok"

    def test_initial_status_is_idle(self):
        data = _api("get", f"/agent/status/{TEST_USER_ID}")
        assert data["status"] == "idle"
        assert data["is_thinking"] is False

    def test_create_microlog_triggers_thinking_cycle(self):
        """
        Step 1: POST a microlog (triggers background agent task).
        Step 2: Poll status — expect 'thinking' within a few seconds.
        Step 3: Wait for it to return to 'idle'.
        """
        # ── Step 1: Create microlog ───────────────────────────
        payload = {
            "user_id": TEST_USER_ID,
            "content": "整合測試：驗證完整的 Agent 思考流程",
            "valence": 0.9,
            "arousal": 0.5,
        }
        result = _api("post", "/micrologs/", json=payload)
        assert result.get("id") or result.get("data")

        # ── Step 2: Poll for 'thinking' ───────────────────────
        found_thinking = False
        for _ in range(8):
            data = _api("get", f"/agent/status/{TEST_USER_ID}")
            if data["status"] == "thinking":
                found_thinking = True
                break
            time.sleep(0.5)

        assert found_thinking, (
            "Never saw 'thinking' status — background task may not have started. "
            "Check that Redis is running and the agent_thinking_task is wired correctly."
        )

        # ── Step 3: Wait for return to 'idle' ────────────────
        back_to_idle = False
        for _ in range(10):
            data = _api("get", f"/agent/status/{TEST_USER_ID}")
            if data["status"] == "idle":
                back_to_idle = True
                break
            time.sleep(0.5)

        assert back_to_idle, "Agent status never returned to 'idle' after thinking."

    def test_get_logs_returns_recent_entry(self):
        """After creating a log above, GET should return it."""
        data = _api("get", f"/micrologs/{TEST_USER_ID}?count=1")
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["user_id"] == TEST_USER_ID
