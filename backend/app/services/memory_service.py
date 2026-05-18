"""
Memory service — composes MemoryRepository + MemoryCache.

Public functions:

  persist_tick(agent, supabase, redis)
      Called as a FastAPI BackgroundTask after each /tick response.
      Serializes the latest PerceptionSummary and writes to Supabase + Redis.

  hydrate_agent(agent, supabase, redis)
      Called once in lifespan.py at startup.
      Restores agent memory from Redis (hot path) or Supabase (cold path).

  retrieve_contextual_memories(current_perception_text, creature_id, supabase, settings)
      Helper — embeds current perception, vector-searches perception_snapshots
      for top-3 relevant past observations, and returns a formatted context
      string for LLM prompts.  Does NOT write to DB.

  run_reflection_cycle(creature_id, supabase, settings, snapshot_limit)
      Toggle-gated (ENABLE_REFLECTION_CYCLE).  Fetches recent snapshots, uses
      gpt-4-turbo to extract dominant_mood / dominant_behavior / summary_text,
      and inserts a row into memory_summaries.

Architecture: Route → Service → Repo → Supabase
              Route → Service → Cache → Redis
The agent package is never imported by repos or other services.
"""

from __future__ import annotations

import json
import logging
import re
import uuid as _uuid_mod
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
from app.core.config import Settings
from app.repositories.memory_cache import MemoryCache
from app.repositories.memory_repo import MemoryRepository
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

_DEFAULT_CREATURE_ID = "cat_01"


# ── UUID helper (mirrors AgentService._to_db_id; no circular import) ────────


def _to_db_id(creature_id: str) -> str:
    try:
        _uuid_mod.UUID(creature_id)
        return creature_id
    except ValueError:
        return str(_uuid_mod.uuid5(_uuid_mod.NAMESPACE_DNS, creature_id))


# ── Serialization helpers ────────────────────────────────────────────────────


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


# ── Public API ───────────────────────────────────────────────────────────────


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

    latest  = recall.recent_perceptions[-1]
    payload = _serialize(latest)

    repo  = MemoryRepository(supabase)
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

    logger.info(
        "Hydrated %d/%d ticks into agent memory for '%s'",
        restored, len(ticks), creature_id,
    )


async def retrieve_contextual_memories(
    current_perception_text: str,
    creature_id: str,
    supabase: Client,
    settings: Settings,
) -> str:
    """
    Embed `current_perception_text`, retrieve the top-3 most similar past
    perception_snapshots via pgvector, and assemble a formatted context string:

        ## Historical Traits
        <latest memory_summaries row, if any>

        ## Relevant Past Observations
        1. <snapshot summary>
        2. <snapshot summary>
        3. <snapshot summary>

        ## Current Perception
        <current_perception_text>

    Returns the formatted string.  Does NOT write to DB.
    Requires a `match_perception_snapshots` RPC function in Supabase.
    """
    db_id     = _to_db_id(creature_id)
    emb_svc   = EmbeddingService(settings)

    # ── Embed current perception ─────────────────────────────────────────────
    try:
        query_embedding = emb_svc.embed_text(current_perception_text)
    except Exception:
        logger.warning(
            "retrieve_contextual_memories: embedding failed — "
            "returning current perception only",
            exc_info=True,
        )
        return f"## Current Perception\n{current_perception_text}"

    sections: list[str] = []

    # ── Historical Traits (latest memory_summaries row) ──────────────────────
    try:
        traits_resp = (
            supabase.table("memory_summaries")
            .select("summary_text, dominant_mood, dominant_behavior")
            .eq("creature_id", db_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if traits_resp.data:
            t = traits_resp.data[0]
            mood_str   = f"{t.get('dominant_mood', 0):.2f}"
            behavior   = t.get("dominant_behavior", "unknown")
            trait_text = t.get("summary_text", "")
            sections.append(
                f"## Historical Traits\n"
                f"Dominant mood: {mood_str}  |  Dominant behavior: {behavior}\n"
                f"{trait_text}"
            )
    except Exception:
        logger.warning("retrieve_contextual_memories: traits fetch failed", exc_info=True)

    # ── Top-3 relevant snapshots (pgvector RPC) ──────────────────────────────
    try:
        snap_resp = supabase.rpc(
            "match_perception_snapshots",
            {
                "query_embedding":    query_embedding,
                "creature_id_filter": db_id,
                "match_count":        3,
            },
        ).execute()

        if snap_resp.data:
            lines = ["## Relevant Past Observations"]
            for i, row in enumerate(snap_resp.data, 1):
                lines.append(f"{i}. {row.get('summary_text', '(no summary)')}")
            sections.append("\n".join(lines))
    except Exception:
        logger.warning(
            "retrieve_contextual_memories: pgvector RPC failed — "
            "ensure match_perception_snapshots function exists in Supabase",
            exc_info=True,
        )

    # ── Current perception ───────────────────────────────────────────────────
    sections.append(f"## Current Perception\n{current_perception_text}")

    return "\n\n".join(sections)


async def run_reflection_cycle(
    creature_id: str,
    supabase: Client,
    settings: Settings,
    snapshot_limit: int = 5,
) -> None:
    """
    Toggle-gated long-term reflection: condenses recent perception snapshots
    into a memory_summaries row using gpt-4-turbo.

    Skips immediately when ENABLE_REFLECTION_CYCLE is False (default).

    Workflow:
      1. Fetch the `snapshot_limit` most recent rows from perception_snapshots.
      2. Build a reflection prompt from their summary_text fields.
      3. Call gpt-4-turbo (JSON mode) to extract:
           dominant_mood     float  [-1.0, 1.0]
           dominant_behavior str    (e.g. "exploration", "hiding")
           summary_text      str    (brief narrative synthesis)
      4. INSERT into memory_summaries with period_start / period_end from the
         fetched snapshots' created_at values.
    """
    if not settings.ENABLE_REFLECTION_CYCLE:
        logger.debug("run_reflection_cycle: ENABLE_REFLECTION_CYCLE=False — skipping")
        return

    db_id = _to_db_id(creature_id)
    logger.info(
        "run_reflection_cycle: START creature=%s  limit=%d",
        creature_id, snapshot_limit,
    )

    # ── Step 1: fetch recent snapshots ───────────────────────────────────────
    try:
        snap_resp = (
            supabase.table("perception_snapshots")
            .select("id, summary_text, created_at")
            .eq("creature_id", db_id)
            .order("created_at", desc=True)
            .limit(snapshot_limit)
            .execute()
        )
    except Exception:
        logger.error(
            "run_reflection_cycle: failed to fetch snapshots for creature=%s",
            creature_id, exc_info=True,
        )
        return

    snapshots = snap_resp.data or []
    if not snapshots:
        logger.info(
            "run_reflection_cycle: no snapshots for creature=%s — skipping",
            creature_id,
        )
        return

    logger.info(
        "run_reflection_cycle: %d snapshot(s) fetched for creature=%s",
        len(snapshots), creature_id,
    )

    # Rows come back newest-first; reverse so the prompt reads chronologically.
    snapshots    = list(reversed(snapshots))
    period_start = snapshots[0].get("created_at", "")
    period_end   = snapshots[-1].get("created_at", "")

    # ── Step 2: build reflection prompt ──────────────────────────────────────
    summary_lines = "\n".join(
        f"{i}. {row.get('summary_text', '(empty)')}"
        for i, row in enumerate(snapshots, 1)
    )
    system_msg = (
        "You are a behavioral analysis assistant for a virtual cat simulation. "
        "Respond ONLY with a valid JSON object — no markdown, no explanation."
    )
    user_msg = (
        "Analyze the following perception snapshots and return a JSON object with "
        "exactly these three keys:\n"
        '  "dominant_mood": a float in [-1.0, 1.0] '
        "(−1 = deeply distressed, +1 = highly content)\n"
        '  "dominant_behavior": a short string label '
        "(e.g. \"exploration\", \"hiding\", \"playing\", \"resting\")\n"
        '  "summary_text": a 1-2 sentence narrative synthesis of the arc\n\n'
        f"Snapshots:\n{summary_lines}"
    )

    # ── Step 3: call LLM (best-effort) ───────────────────────────────────────
    # If the LLM call succeeds, use its structured output.
    # If it fails or times out, fall back to an algorithmic summary built
    # directly from the snapshot texts so the INSERT always happens.
    dominant_mood     = 0.0
    dominant_behavior = "unknown"
    summary_text      = ""

    try:
        from app.agent.llm_provider import create_llm_provider
        from langchain_core.messages import HumanMessage, SystemMessage

        llm      = create_llm_provider(settings.llm)
        response = await llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=user_msg),
        ])
        raw = response.content.strip()
        logger.info(
            "run_reflection_cycle: LLM raw response for creature=%s: %.300s",
            creature_id, raw,
        )

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object in response: {raw!r:.100}")
        data: dict[str, Any] = json.loads(match.group())

        dominant_mood     = max(-1.0, min(1.0, float(data.get("dominant_mood", 0.0))))
        dominant_behavior = str(data.get("dominant_behavior", "unknown"))[:64]
        summary_text      = str(data.get("summary_text", ""))
        logger.info(
            "run_reflection_cycle: LLM extraction OK for creature=%s  "
            "mood=%.2f  behavior=%s",
            creature_id, dominant_mood, dominant_behavior,
        )

    except Exception:
        logger.warning(
            "run_reflection_cycle: LLM call failed for creature=%s — "
            "using algorithmic fallback",
            creature_id, exc_info=True,
        )

    # ── Step 4: algorithmic fallback if LLM didn't produce a summary ──────────
    if not summary_text:
        texts = [
            s.get("summary_text", "").strip()
            for s in snapshots
            if s.get("summary_text", "").strip()
        ]
        if texts:
            summary_text = " → ".join(texts)
        else:
            summary_text = (
                f"Aggregated {len(snapshots)} perception snapshot(s) "
                f"for creature {creature_id}."
            )
        dominant_behavior = "unknown"
        dominant_mood     = 0.0
        logger.info(
            "run_reflection_cycle: fallback summary built for creature=%s  "
            "len=%d chars",
            creature_id, len(summary_text),
        )

    # ── Step 5: insert into memory_summaries ─────────────────────────────────
    try:
        supabase.table("memory_summaries").insert(
            {
                "creature_id":       db_id,
                "period_start":      period_start,
                "period_end":        period_end,
                "dominant_mood":     dominant_mood,
                "dominant_behavior": dominant_behavior,
                "summary_text":      summary_text,
            }
        ).execute()
        logger.info(
            "[REFLECTION DONE] memory_summaries INSERT — creature=%s  "
            "mood=%.2f  behavior=%s  snapshots=%d",
            creature_id, dominant_mood, dominant_behavior, len(snapshots),
        )
    except Exception:
        logger.error(
            "run_reflection_cycle: memory_summaries INSERT failed for creature=%s",
            creature_id, exc_info=True,
        )
