"""
Memory service — composes MemoryRepository + MemoryCache.

Public functions:

  persist_tick(agent, supabase, redis)
      Called as a FastAPI BackgroundTask after each /tick response.
      Serializes the latest PerceptionSummary and writes to Supabase + Redis.

  hydrate_agent(agent, supabase, redis)
      Called once in lifespan.py at startup.
      Restores agent memory from Redis (hot path) or Supabase (cold path).

  log_contextual_decision(action, reasoning, perception_ctx, supabase)
      Stores the agent's decision in the micrologs table using Anthropic's
      Contextual Retrieval framing: situational context is prepended to the
      decision text so each log record is self-contained for future retrieval.
      Fire-and-forget — never raises; errors are logged and swallowed.

Architecture: Route → Service → Repo → Supabase
              Route → Service → Cache → Redis
"""

import logging
import uuid
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


# ── Contextual decision logging ─────────────────────────────────────────────
# Implements Anthropic's Contextual Retrieval pattern:
# each stored record prepends a situational context header so the log entry
# is self-contained and meaningful when retrieved out of order.

# Deterministic UUID namespace so creature log entries have stable user_ids.
_CREATURE_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _build_context_header(perception_ctx: dict) -> str:
    """Build the situational context prefix (Contextual Retrieval framing)."""
    if not perception_ctx:
        return "[Context: no perception data]"

    tick    = perception_ctx.get("tick", 0)
    threat  = perception_ctx.get("threat_level", "safe").upper()
    pos     = perception_ctx.get("creature", {}).get("position", {})
    env     = perception_ctx.get("environment", {})
    n_ents  = perception_ctx.get("entity_count", 0)

    return (
        f"[Context: tick={tick} | threat={threat} | "
        f"pos=({pos.get('x', 0):.1f}, {pos.get('z', 0):.1f}) | "
        f"weather={env.get('weather', 'unknown')} | "
        f"entities_nearby={n_ents}]"
    )


def _estimate_valence(action: str, perception_ctx: dict) -> float:
    """
    Rough valence score for the micrologs row.
    Negative = aversive / threat response; positive = approach / play.
    """
    threat = perception_ctx.get("threat_level", "safe")
    if threat == "danger":
        return -0.7
    if action in ("Attack1",):
        return -0.2
    if action in ("Jump", "Sprint"):
        return 0.4
    if action == "wait":
        return 0.0
    return 0.15   # mild positive for exploratory movement


def _estimate_arousal(action: str, perception_ctx: dict) -> float:
    """
    Rough arousal score: 0 = calm, 1 = maximally activated.
    """
    threat = perception_ctx.get("threat_level", "safe")
    if threat == "danger":
        return 0.9
    if action in ("Sprint", "Attack1"):
        return 0.7
    if action == "Jump":
        return 0.5
    if action == "move":
        return 0.3
    return 0.1


async def log_contextual_decision(
    *,
    action: str,
    reasoning: str,
    perception_ctx: dict,
    supabase: Client,
    creature_id: str = _DEFAULT_CREATURE_ID,
) -> None:
    """
    Store the agent's LLM decision in the micrologs table.

    Content layout (Contextual Retrieval pattern):
        [Context: tick=N | threat=X | pos=(x,z) | …]

        Action: <name>
        Reasoning: <LLM's internal monologue>

    A deterministic UUID derived from creature_id is used as user_id so the
    system can write without a human user being present.

    Errors are caught and logged — this must never block the Unity response.
    """
    try:
        context_header = _build_context_header(perception_ctx)
        content = (
            f"{context_header}\n\n"
            f"Action: {action}\n"
            f"Reasoning: {reasoning}"
        )

        system_user_id = str(uuid.uuid5(_CREATURE_NS, creature_id))

        supabase.table("micrologs").insert({
            "user_id":  system_user_id,
            "content":  content,
            "valence":  _estimate_valence(action, perception_ctx),
            "arousal":  _estimate_arousal(action, perception_ctx),
        }).execute()

        logger.debug(
            "Logged contextual decision for '%s': action=%s",
            creature_id, action,
        )
    except Exception:
        logger.error(
            "Failed to log contextual decision for '%s'", creature_id, exc_info=True
        )
