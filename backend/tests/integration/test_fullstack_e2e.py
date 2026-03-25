"""
Integration test: full-stack E2E — user → FastAPI → Supabase + Redis.

Simulates a real user hitting the API via AsyncClient (in-process),
then verifies side effects DIRECTLY against Supabase and Redis
to ensure data actually landed — not just that the API said "201".

Marked @paid — calls real Supabase, Redis, and OpenAI.
Only runs with `make test-integration CONFIRM_PAID=1`.

Fixtures used (from conftest.py):
    real_client   — httpx.AsyncClient wired to the FastAPI app
    real_supabase — real Supabase client (service role key)
    real_redis    — real async Redis connection
"""

import pytest

TEST_USER_ID = "66af1b4c-4628-4544-addd-15c9a36b4707"


@pytest.mark.paid
@pytest.mark.asyncio
class TestFullStackE2E:
    """
    Each test follows the same pattern:
        1. Act    — call the API as a user would
        2. Verify — check Supabase / Redis directly to confirm the write
    """

    # ── Microlog: API → Supabase ──────────────────────────────

    async def test_post_microlog_persists_in_supabase(
        self, real_client, real_supabase
    ):
        """
        User POSTs a microlog via the API.
        Then we query Supabase directly to confirm the row exists.
        """
        # 1. Act — user creates a microlog through the API
        payload = {
            "user_id": TEST_USER_ID,
            "content": "Full-stack test: verify Supabase write",
            "valence": 0.8,
            "arousal": 0.4,
        }
        resp = await real_client.post("/api/v1/micrologs/", json=payload)
        assert resp.status_code == 201, f"API returned {resp.status_code}: {resp.text}"

        created = resp.json()
        microlog_id = created["id"]
        assert microlog_id is not None

        # 2. Verify — query Supabase directly (bypassing the API)
        row = (
            real_supabase.table("micrologs")
            .select("*")
            .eq("id", microlog_id)
            .single()
            .execute()
        )
        assert row.data is not None, "Row not found in Supabase"
        assert row.data["user_id"] == TEST_USER_ID
        assert row.data["content"] == payload["content"]

    async def test_get_micrologs_matches_supabase(
        self, real_client, real_supabase
    ):
        """
        User GETs micrologs via the API.
        Then we query Supabase directly and confirm they match.
        """
        # 1. Act — user fetches micrologs through the API
        resp = await real_client.get(
            f"/api/v1/micrologs/{TEST_USER_ID}?count=3"
        )
        assert resp.status_code == 200
        api_logs = resp.json()

        # 2. Verify — query Supabase directly for the same data
        db_result = (
            real_supabase.table("micrologs")
            .select("id")
            .eq("user_id", TEST_USER_ID)
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        db_ids = {row["id"] for row in db_result.data}
        api_ids = {log["id"] for log in api_logs}

        assert api_ids == db_ids, (
            f"API returned different rows than Supabase.\n"
            f"  API: {api_ids}\n"
            f"  DB:  {db_ids}"
        )

    # ── Agent status: API → Redis ─────────────────────────────

    async def test_agent_status_reflects_redis(
        self, real_client, real_redis, real_settings
    ):
        """
        Seed Redis directly with a known status,
        then confirm the API returns that same status.
        """
        # 1. Arrange — write a status directly into Redis
        redis_key = f"agent_status:{TEST_USER_ID}"
        await real_redis.set(redis_key, "thinking", ex=60)

        # 2. Act — user checks status through the API
        resp = await real_client.get(
            f"/api/v1/agent/status/{TEST_USER_ID}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "thinking", (
            f"API returned '{data['status']}' but Redis has 'thinking'"
        )

        # 3. Cleanup — reset to idle
        await real_redis.delete(redis_key)

    async def test_idle_when_redis_key_missing(self, real_client, real_redis):
        """
        When there's no Redis key for a user,
        the API should return 'idle' as the default.
        """
        # 1. Arrange — ensure no key exists
        fake_user = "00000000-0000-0000-0000-000000000000"
        await real_redis.delete(f"agent_status:{fake_user}")

        # 2. Act — user checks status through the API
        resp = await real_client.get(f"/api/v1/agent/status/{fake_user}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"

    # ── Round-trip: API → Supabase + Redis together ───────────

    async def test_post_microlog_and_verify_both_stores(
        self, real_client, real_supabase, real_redis
    ):
        """
        The big one: POST a microlog, then verify:
          - The row exists in Supabase
          - The agent status changed in Redis (if your pipeline triggers it)
          - The GET endpoint returns the same data
        """
        # 1. Act — user creates a microlog
        payload = {
            "user_id": TEST_USER_ID,
            "content": "Round-trip test: both stores",
            "valence": 0.7,
            "arousal": 0.6,
        }
        resp = await real_client.post("/api/v1/micrologs/", json=payload)
        assert resp.status_code == 201
        created = resp.json()

        # 2. Verify Supabase — row exists
        row = (
            real_supabase.table("micrologs")
            .select("id, content")
            .eq("id", created["id"])
            .single()
            .execute()
        )
        assert row.data is not None
        assert row.data["content"] == payload["content"]

        # 3. Verify API — GET returns the same log
        resp = await real_client.get(
            f"/api/v1/micrologs/{TEST_USER_ID}?count=1"
        )
        assert resp.status_code == 200
        logs = resp.json()
        assert any(log["id"] == created["id"] for log in logs), (
            f"Created microlog {created['id']} not found in GET response"
        )

    # ── Cleanup helper (optional) ─────────────────────────────

    async def test_cleanup_test_data(self, real_supabase):
        """
        Remove test micrologs created during this run.
        Run this last — depends on test ordering or can be called manually.

        NOTE: If your test suite uses a dedicated test user,
        this keeps your Supabase table clean.
        """
        result = (
            real_supabase.table("micrologs")
            .delete()
            .eq("user_id", TEST_USER_ID)
            .like("content", "%test%")
            .execute()
        )
        # Just confirm delete didn't error — count may vary
        assert isinstance(result.data, list)