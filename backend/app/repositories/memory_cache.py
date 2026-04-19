"""
Agent memory cache — Redis layer for hot tick reads.

Stores the last N serialized perception dicts in a Redis list per creature.
Falls back gracefully on any Redis error — the DB is the source of truth.

Key format:  agent:ticks:{creature_id}   (RPUSH, newest at right)
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "agent:ticks:"
_MAX_CACHED_TICKS = 50


class MemoryCache:
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    def _key(self, creature_id: str) -> str:
        return f"{_KEY_PREFIX}{creature_id}"

    async def push_tick(self, creature_id: str, perception: dict[str, Any]) -> None:
        """Append a tick to the right of the list, then trim to max size."""
        key = self._key(creature_id)
        try:
            await self._redis.rpush(key, json.dumps(perception))
            await self._redis.ltrim(key, -_MAX_CACHED_TICKS, -1)
        except Exception:
            logger.warning(
                "Redis write failed for %s — continuing without cache", creature_id,
                exc_info=True,
            )

    async def load_ticks(
        self,
        creature_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Return up to `limit` ticks in chronological order (oldest first).
        Returns an empty list on cache miss or Redis error.
        """
        key = self._key(creature_id)
        try:
            raw = await self._redis.lrange(key, -limit, -1)
            return [json.loads(entry) for entry in raw]
        except Exception:
            logger.warning(
                "Redis read failed for %s — returning empty", creature_id,
                exc_info=True,
            )
            return []

    async def clear(self, creature_id: str) -> None:
        try:
            await self._redis.delete(self._key(creature_id))
        except Exception:
            logger.warning("Redis delete failed for %s", creature_id, exc_info=True)
