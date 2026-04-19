"""
Agent service — two responsibilities:

1. Redis job lifecycle: enqueue → complete/fail → consume (Unity polling).
2. Snapshot pre-processing: convert raw Unity JSON to an LLM-ready text prompt
   before the graph runs (useful for debugging, evals, and prompt caching).
"""

import json
import logging

import redis.asyncio as aioredis

from app.core.config import Settings

logger = logging.getLogger(__name__)


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

        if raw is None or raw == "pending":
            return {"status": "pending"}

        data = json.loads(raw)
        if data.get("status") in ("done", "error"):
            await self._redis.delete(f"job:{job_id}")
        return data

    # ─── Snapshot processing ─────────────────────────────────────────────────

    @staticmethod
    def snapshot_to_prompt(raw_payload: dict) -> str:
        """
        Convert a raw Unity snapshot dict into a clean, human-readable text
        string suitable for direct inclusion in an LLM prompt.

        Uses SnapshotManager to validate and interpret the data (threat
        assessment, entity filtering) — the same logic the graph uses, but
        without side effects (no tick counter increment, no memory write).

        Safe to call before the graph runs, e.g. for logging, evals, or
        prompt-cache warm-up.
        """
        from app.agent.perception import SnapshotManager
        from app.agent.schemas.perception_schema import PerceptionError
        from app.agent.prompts import format_perception_for_prompt

        eye = SnapshotManager(relevance_radius=30.0, threat_radius=10.0)
        result = eye.process(raw_payload)

        if isinstance(result, PerceptionError):
            logger.debug("snapshot_to_prompt: perception error — %s", result.message)
            return f"[Perception error: {result.message}]"

        return format_perception_for_prompt(result.to_prompt_context())
