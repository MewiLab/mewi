from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.agent.schemas.place_memory_schema import PlaceMemoryEntry, PlaceMemoryOverlay

logger = logging.getLogger(__name__)

_KEY_PREFIX = "agent:place_overlay:"
_META_FIELD = "__meta__"

_RECORD_VISIT_SCRIPT = """
local key = KEYS[1]
local zone_id = ARGV[1]
local now = tonumber(ARGV[2]) or 0
local request_id = ARGV[3] or ""
local refresh_seconds = tonumber(ARGV[4]) or 30
local ttl_seconds = tonumber(ARGV[5]) or 604800
local meta_field = ARGV[6]

if zone_id == "" then
    return "missing_zone"
end

local meta_raw = redis.call("HGET", key, meta_field)
local last_zone = ""
if meta_raw then
    local ok, meta = pcall(cjson.decode, meta_raw)
    if ok and meta then
        last_zone = meta["last_zone_id"] or ""
    end
end

local entry_raw = redis.call("HGET", key, zone_id)
local entry = nil
if entry_raw then
    local ok, decoded = pcall(cjson.decode, entry_raw)
    if ok and decoded then
        entry = decoded
    end
end

if not entry then
        entry = {
            zone_id = zone_id,
            visit_count = 0,
            last_visited_at = 0,
            last_seen_at = 0,
            familiarity = 0,
            last_arrival_request_id = ""
        }
end

local visit_count = tonumber(entry["visit_count"]) or 0
local last_visited_at = tonumber(entry["last_visited_at"]) or 0
local should_count = last_zone ~= zone_id
local should_refresh = should_count or ((now - last_visited_at) >= refresh_seconds)

if should_count then
    visit_count = visit_count + 1
end

if should_refresh then
    entry["visit_count"] = visit_count
    entry["last_visited_at"] = now
    entry["last_seen_at"] = now
    entry["familiarity"] = math.min(1, visit_count / 8)
    entry["last_arrival_request_id"] = request_id
    redis.call("HSET", key, zone_id, cjson.encode(entry))
end

local meta = {
    last_zone_id = zone_id,
    last_observed_at = now,
    last_request_id = request_id
}
redis.call("HSET", key, meta_field, cjson.encode(meta))
redis.call("EXPIRE", key, ttl_seconds)

return should_count and "counted" or "refreshed"
"""


class PlaceMemoryCache:
    """Redis-backed hot store for per-creature place coverage.

    Each creature owns one hash key. The write path is a Lua script so the
    "did the current zone change?" check and the visit-count increment land
    atomically. Today the agent worker already serializes ticks per creature,
    so single-process races are not possible — but the script is what keeps
    the invariant intact if a second worker process is ever added or Unity
    starts pipelining ticks.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        ttl_seconds: int = 604_800,
        refresh_seconds: float = 30.0,
    ) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._refresh_seconds = refresh_seconds

    async def record_visit(
        self,
        creature_id: str,
        zone_id: str,
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        await self._redis.eval(
            _RECORD_VISIT_SCRIPT,
            1,
            self._key(creature_id),
            zone_id,
            str(observed_at),
            request_id,
            str(self._refresh_seconds),
            str(self._ttl_seconds),
            _META_FIELD,
        )

    async def load_overlay(self, creature_id: str) -> PlaceMemoryOverlay:
        raw = await self._redis.hgetall(self._key(creature_id))
        entries: dict[str, PlaceMemoryEntry] = {}

        for raw_field, raw_value in raw.items():
            field = self._decode(raw_field)
            if field == _META_FIELD:
                continue

            try:
                data = json.loads(self._decode(raw_value))
                entry = PlaceMemoryEntry.from_dict(data)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping malformed place memory entry creature_id=%s field=%s",
                    creature_id,
                    field,
                    exc_info=True,
                )
                continue

            if entry.zone_id:
                entries[entry.zone_id] = entry

        return PlaceMemoryOverlay(entries=entries)

    @staticmethod
    def _key(creature_id: str) -> str:
        return f"{_KEY_PREFIX}{creature_id}"

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode() if isinstance(value, bytes) else str(value)
