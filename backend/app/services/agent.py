"""
Agent service — reads/writes the agent's real-time status in Redis.
"""

import redis.asyncio as aioredis

from app.core.config import Settings


class AgentService:
    def __init__(self, redis: aioredis.Redis, settings: Settings):
        self._redis = redis
        self._ttl = settings.agent_status_ttl

    async def set_status(self, user_id: str, status: str) -> None:
        await self._redis.set(f"agent_status:{user_id}", status, ex=self._ttl)

    async def get_status(self, user_id: str) -> str:
        value = await self._redis.get(f"agent_status:{user_id}")
        return value or "idle"