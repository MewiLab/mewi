"""
Agent service — reads/writes the agent's real-time status and job results in Redis.
"""

import json

import redis.asyncio as aioredis

from app.core.config import Settings


class AgentService:
    def __init__(self, redis: aioredis.Redis, settings: Settings):
        self._redis = redis
        self._ttl = settings.agent_status_ttl
        self._job_ttl = settings.agent_job_ttl

    # ─── Agent status ────────────────────────────────────────────────────────

    async def set_status(self, user_id: str, status: str) -> None:
        await self._redis.set(f"agent_status:{user_id}", status, ex=self._ttl)

    async def get_status(self, user_id: str) -> str:
        value = await self._redis.get(f"agent_status:{user_id}")
        return value or "idle"

    # ─── Async tick jobs ─────────────────────────────────────────────────────

    async def enqueue_job(self, job_id: str) -> None:
        """Mark a job as pending before the background worker starts."""
        await self._redis.set(f"job:{job_id}", "pending", ex=self._job_ttl)

    async def complete_job(self, job_id: str, result: dict) -> None:
        """Write a successful result so Unity can consume it."""
        await self._redis.set(
            f"job:{job_id}", json.dumps({"status": "done", **result}), ex=self._job_ttl
        )

    async def fail_job(self, job_id: str) -> None:
        """Write an explicit error so Unity aborts polling immediately."""
        await self._redis.set(
            f"job:{job_id}", json.dumps({"status": "error"}), ex=self._job_ttl
        )

    async def consume_job(self, job_id: str) -> dict:
        """
        Read job state and delete the key if the job is terminal.

        Returns one of:
          {"status": "pending"}          — still running
          {"status": "done", …}          — result payload; key deleted
          {"status": "error"}            — backend failure; key deleted
          {"status": "pending"}          — key missing (expired or unknown)
        """
        raw = await self._redis.get(f"job:{job_id}")

        if raw is None or raw == b"pending":
            return {"status": "pending"}

        data = json.loads(raw)
        if data.get("status") in ("done", "error"):
            await self._redis.delete(f"job:{job_id}")
        return data
