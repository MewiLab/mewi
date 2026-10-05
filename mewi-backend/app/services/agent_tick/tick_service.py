"""Redis-backed queue for shared Unity agent ticks."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.core.config import Settings

AGENT_TICK_SCHEMA = "agent_tick.v2"
JOB_QUEUE_KEY = "agent:tick:queue"
JOB_KEY = "agent:tick:job:{job_id}"
IN_FLIGHT_KEY = "agent:tick:inflight:{creature_id}"
JOB_POLL_INTERVAL_SECONDS = 0.25
JOB_WAIT_TIMEOUT_SECONDS = 0.0
RELEASE_IN_FLIGHT_SCRIPT = """
local raw = redis.call("GET", KEYS[1])
if not raw then
  return 0
end

local ok, data = pcall(cjson.decode, raw)
if ok and data and tostring(data["request_id"] or "") == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end

if not ok and raw == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end

return 0
""".strip()

logger = logging.getLogger(__name__)


class AgentTickInFlightError(RuntimeError):
    def __init__(self, creature_id: str, request_id: str, existing: dict[str, Any]):
        self.creature_id = creature_id
        self.request_id = request_id
        self.existing_job_id = str(existing.get("job_id") or "")
        self.existing_request_id = str(existing.get("request_id") or "")
        super().__init__(
            f"in_flight: previous request still pending ({self.existing_request_id or self.existing_job_id})"
        )


class AgentTickService:
    def __init__(self, redis: aioredis.Redis, settings: Settings, **_: Any):
        self._redis = redis
        self._ttl = settings.agent_status_ttl

    async def submit_tick(self, creature_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        creature_id = self._clean(creature_id)
        request_id = self._clean(payload.get("requestId") or payload.get("request_id"))
        if not creature_id:
            raise ValueError("creature_id is required")
        if not request_id:
            raise ValueError("requestId is required")

        now = datetime.now(timezone.utc).isoformat()
        job_id = str(uuid.uuid4())
        reservation = {
            "schema": AGENT_TICK_SCHEMA,
            "creature_id": creature_id,
            "request_id": request_id,
            "job_id": job_id,
            "reserved_at": now,
        }

        reserved = await self._redis.set(
            self._in_flight_key(creature_id),
            json.dumps(reservation),
            ex=self._ttl,
            nx=True,
        )
        if not reserved:
            existing = await self.get_in_flight(creature_id)
            logger.warning(
                "Agent tick rejected in-flight duplicate creature_id=%s request_id=%s existing_request_id=%s",
                creature_id,
                request_id,
                (existing or {}).get("request_id", ""),
            )
            raise AgentTickInFlightError(creature_id, request_id, existing or {})

        job = {
            "schema": AGENT_TICK_SCHEMA,
            "type": "agent_tick",
            "job_id": job_id,
            "creature_id": creature_id,
            "request_id": request_id,
            "status": "queued",
            "payload": payload,
            "queued_at": now,
        }
        try:
            await self._redis.set(self._job_key(job_id), json.dumps(job), ex=self._ttl)
            queue_depth = await self._redis.rpush(JOB_QUEUE_KEY, json.dumps(job))
        except Exception:
            await self.release_in_flight(creature_id, request_id)
            logger.exception(
                "Agent tick Redis enqueue failed creature_id=%s request_id=%s job_id=%s",
                creature_id,
                request_id,
                job_id,
            )
            raise

        logger.info(
            "Agent tick job queued creature_id=%s request_id=%s job_id=%s queue_depth=%s",
            creature_id,
            request_id,
            job_id,
            queue_depth,
        )

        return {
            "schema": AGENT_TICK_SCHEMA,
            "job_id": job_id,
            "creature_id": creature_id,
            "request_id": request_id,
            "status": "queued",
            "queue_depth": queue_depth,
        }

    async def get_next_job(self, timeout: int = 5) -> dict[str, Any] | None:
        item = await self._redis.blpop(JOB_QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        _key, raw = item
        return json.loads(self._decode(raw))

    async def mark_processing(self, creature_id: str, job_id: str) -> None:
        await self._merge_job(job_id, {
            "status": "processing",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

    async def publish_result(self, creature_id: str, job_id: str, result: dict[str, Any]) -> None:
        row = {
            "status": "done",
            **result,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        job = await self._merge_job(job_id, row)
        released = await self.release_in_flight(
            str(job.get("creature_id") or creature_id),
            str(job.get("request_id") or result.get("request_id") or ""),
        )
        logger.info(
            "Agent tick job completed creature_id=%s request_id=%s job_id=%s in_flight_released=%s",
            job.get("creature_id") or creature_id,
            job.get("request_id") or result.get("request_id") or "",
            job_id,
            released,
        )

    async def publish_error(self, creature_id: str, job_id: str, reason: str) -> None:
        row = {
            "status": "error",
            "error": reason,
            "reasoning": reason,
            "action_result": {"status": "done", "action": "idle", "target": ""},
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        job = await self._merge_job(job_id, row)
        released = await self.release_in_flight(
            str(job.get("creature_id") or creature_id),
            str(job.get("request_id") or ""),
        )
        logger.warning(
            "Agent tick job failed creature_id=%s request_id=%s job_id=%s in_flight_released=%s reason=%s",
            job.get("creature_id") or creature_id,
            job.get("request_id") or "",
            job_id,
            released,
            reason,
        )

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._job_key(job_id))
        if not raw:
            return None
        return json.loads(self._decode(raw))

    async def wait_for_final_job(
        self,
        job_id: str,
        timeout_seconds: float = JOB_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = JOB_POLL_INTERVAL_SECONDS,
    ) -> dict[str, Any] | None:
        import asyncio

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds if timeout_seconds > 0 else None

        while deadline is None or loop.time() < deadline:
            job = await self.get_job(job_id)
            if job and job.get("status") in {"done", "error"}:
                return job
            await asyncio.sleep(poll_interval_seconds)

        return None

    async def get_in_flight(self, creature_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._in_flight_key(creature_id))
        if not raw:
            return None
        try:
            return json.loads(self._decode(raw))
        except json.JSONDecodeError:
            return {"request_id": self._decode(raw)}

    async def release_in_flight(self, creature_id: str, request_id: str) -> bool:
        request_id = self._clean(request_id)
        existing = await self.get_in_flight(creature_id)
        if not existing:
            return False
        if self._clean(existing.get("request_id")) != request_id:
            logger.warning(
                "Agent tick in-flight release skipped creature_id=%s request_id=%s existing_request_id=%s",
                creature_id,
                request_id,
                existing.get("request_id", ""),
            )
            return False
        deleted = await self._redis.eval(
            RELEASE_IN_FLIGHT_SCRIPT,
            1,
            self._in_flight_key(creature_id),
            request_id,
        )
        return bool(deleted)

    async def _merge_job(self, job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = await self.get_job(job_id) or {"job_id": job_id}
        current.update(patch)
        await self._redis.set(self._job_key(job_id), json.dumps(current), ex=self._ttl)
        return current

    @staticmethod
    def _job_key(job_id: str) -> str:
        return JOB_KEY.format(job_id=job_id)

    @staticmethod
    def _in_flight_key(creature_id: str) -> str:
        return IN_FLIGHT_KEY.format(creature_id=creature_id)

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode() if isinstance(value, bytes) else value

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()
