import json
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.core.config import Settings

JOB_QUEUE_KEY = "agent:jobs"
JOB_KEY = "agent:job:{job_id}"
STATUS_KEY = "agent:status:{creature_id}"
LATEST_JOB_KEY = "agent:latest_job:{creature_id}"


class AgentTickService:
    def __init__(self, redis: aioredis.Redis, settings: Settings, **_: Any):
        self._redis = redis
        self._ttl = settings.agent_status_ttl

    async def submit_tick(self, creature_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        job = {
            "job_id": str(uuid.uuid4()),
            "creature_id": creature_id,
            "request_id": payload.get("requestId", ""),
            "status": "queued",
            "payload": payload,
            "queued_at": now,
        }
        await self._redis.set(self._job_key(job["job_id"]), json.dumps(job), ex=self._ttl)
        queue_depth = await self._redis.rpush(JOB_QUEUE_KEY, json.dumps(job))
        await self._redis.set(STATUS_KEY.format(creature_id=creature_id), "queued", ex=self._ttl)
        await self._redis.set(LATEST_JOB_KEY.format(creature_id=creature_id), job["job_id"], ex=self._ttl)
        return {
            "job_id": job["job_id"],
            "creature_id": creature_id,
            "request_id": job["request_id"],
            "status": "queued",
            "queue_depth": queue_depth,
        }

    async def get_next_job(self, timeout: int = 5) -> dict[str, Any] | None:
        item = await self._redis.blpop(JOB_QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        _key, raw = item
        return json.loads(self._decode(raw))

    async def _set_status(self, creature_id: str, status: str) -> None:
        await self._redis.set(STATUS_KEY.format(creature_id=creature_id), status, ex=self._ttl)

    async def mark_processing(self, creature_id: str, job_id: str) -> None:
        await self._merge_job(job_id, {
            "status": "processing",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        await self._set_status(creature_id, "processing")

    async def publish_result(self, creature_id: str, job_id: str, result: dict[str, Any]) -> None:
        row = {
            "status": "done",
            **result,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._merge_job(job_id, row)
        await self._redis.set(STATUS_KEY.format(creature_id=creature_id), row["status"], ex=self._ttl)

    async def publish_error(self, creature_id: str, job_id: str, reason: str) -> None:
        row = {
            "status": "error",
            "error": reason,
            "reasoning": reason,
            "action_result": {"status": "done", "action": "idle", "x": 0.0, "y": 0.0, "z": 0.0, "target": ""},
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._merge_job(job_id, row)
        await self._redis.set(STATUS_KEY.format(creature_id=creature_id), "error", ex=self._ttl)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._job_key(job_id))
        if not raw:
            return None
        return json.loads(self._decode(raw))

    async def _merge_job(self, job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = await self.get_job(job_id) or {"job_id": job_id}
        current.update(patch)
        await self._redis.set(self._job_key(job_id), json.dumps(current), ex=self._ttl)
        return current

    @staticmethod
    def _job_key(job_id: str) -> str:
        return JOB_KEY.format(job_id=job_id)

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode() if isinstance(value, bytes) else value
