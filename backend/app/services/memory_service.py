"""
Memory service — composes MemoryRepository + MemoryCache.

Two public functions wired into the app lifecycle:

  persist_tick(agent, supabase, redis)
      Called as a FastAPI BackgroundTask after each /tick response.
      Serializes the latest PerceptionSummary and writes to Supabase + Redis.

  hydrate_agent(agent, supabase, redis)
      Called once in lifespan.py at startup.
      Restores agent memory from Redis (hot path) or Supabase (cold path).

Architecture: Route → Service → Repo → Supabase
              Route → Service → Cache → Redis
The agent package is never imported by repos or other services.
"""

import logging
from typing import Any, Dict

import redis.asyncio as aioredis
from supabase import Client

from app.agent.creature_agent import CreatureAgent
from app.agent.schemas.perception_schema import (
    CreatureSnapshot,
    EntityObservation,
    EnvironmentSnapshot,
    PerceptionSummary,
    ThreatLevel,
)
from app.repositories.memory_cache import MemoryCache
from app.repositories.memory_repo import MemoryRepository

logger = logging.getLogger(__name__)

# Matches the creature seeded in your DB / Unity config.
_DEFAULT_CREATURE_ID = "cat_01"


# ── Serialization helpers ───────────────────────────────────────────────────


def _serialize(summary: PerceptionSummary) -> Dict[str, Any]:
    return {
        "tick": summary.tick,
        "threat_level": summary.threat_level.value,
        "creature": summary.creature.model_dump(),
        "environment": summary.environment.model_dump(),
        "nearby_entities": [e.model_dump() for e in summary.nearby_entities],
    }


def _deserialize(data: Dict[str, Any]) -> PerceptionSummary:
    return PerceptionSummary(
        tick=data["tick"],
        threat_level=ThreatLevel(data["threat_level"]),
        creature=CreatureSnapshot(**data["creature"]),
        environment=EnvironmentSnapshot(**data["environment"]),
        nearby_entities=[EntityObservation(**e) for e in data.get("nearby_entities", [])],
    )


# ── Public API ──────────────────────────────────────────────────────────────


async def persist_tick(
    agent: CreatureAgent,
    supabase: Client,
    redis: aioredis.Redis,
    creature_id: str = _DEFAULT_CREATURE_ID,
) -> None:
    """
    Serialize the agent's latest perception tick and write it to both
    Supabase (durable) and Redis (hot cache).

    Runs as a FastAPI BackgroundTask — never blocks the HTTP response.
    Errors are logged but never re-raised so Unity is never blocked.
    """
    recall = agent.memory.recall()
    if not recall.recent_perceptions:
        return

    latest = recall.recent_perceptions[-1]
    payload = _serialize(latest)

    repo = MemoryRepository(supabase)
    cache = MemoryCache(redis)

    try:
        repo.save_tick(creature_id=creature_id, tick=latest.tick, perception=payload)
    except Exception:
        logger.error("Failed to persist tick %d to Supabase", latest.tick, exc_info=True)

    await cache.push_tick(creature_id=creature_id, perception=payload)


async def hydrate_agent(
    agent: CreatureAgent,
    supabase: Client,
    redis: aioredis.Redis,
    creature_id: str = _DEFAULT_CREATURE_ID,
    limit: int = 50,
) -> None:
    """
    Restore agent memory from the last session.

    Hot path: Redis list → already serialized, fast.
    Cold path: Supabase table → on first boot or after cache eviction.
              Also back-fills Redis so the next restart is a cache hit.

    Each deserialized PerceptionSummary is replayed into agent.memory.record()
    which also restores the spatial log as a side-effect.
    """
    cache = MemoryCache(redis)
    ticks: list[Dict[str, Any]] = await cache.load_ticks(creature_id=creature_id, limit=limit)

    if not ticks:
        logger.info("Cache miss for '%s' — hydrating from Supabase", creature_id)
        repo = MemoryRepository(supabase)
        try:
            rows = repo.load_recent_ticks(creature_id=creature_id, limit=limit)
        except Exception:
            logger.error("Failed to hydrate from Supabase", exc_info=True)
            return

        # Back-fill Redis so next restart hits the cache
        for row in rows:
            await cache.push_tick(creature_id=creature_id, perception=row["perception"])

        ticks = [row["perception"] for row in rows]

    restored = 0
    for tick_data in ticks:
        try:
            summary = _deserialize(tick_data)
            agent.memory.record(summary)
            restored += 1
        except Exception:
            logger.warning(
                "Skipping malformed tick during hydration: %s", tick_data, exc_info=True
            )

    logger.info("Hydrated %d/%d ticks into agent memory for '%s'", restored, len(ticks), creature_id)
