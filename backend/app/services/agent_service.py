"""
AgentService — orchestrates one full agent tick with semantic aggregation.

Architecture: per-request instance + shared state
  get_agent_service (deps.py) creates a fresh AgentService on every request,
  injecting request-scoped deps (redis, supabase, agent, graph) cleanly.
  Persistent cross-request data lives in AgentServiceState, which is a
  process-scoped singleton injected at construction time.

Buffer strategy (Redis LIST + feature toggle):
  Raw Unity payloads are pushed as JSON to a Redis LIST key
  `cat:buffer:{creature_id}`.  A per-creature asyncio.Lock in
  AgentServiceState serialises concurrent pushes.

  When ENABLE_MEMORY_PIPELINE is False (default) — every tick returns
  {"status": "buffering", "count": N} immediately.  Zero LLM / DB cost.

  When ENABLE_MEMORY_PIPELINE is True — two flush triggers are active:
    Count trigger  : LLEN >= aggregation_limit → BackgroundTask flush.
    Timer trigger  : 1st item in an empty list → 120-second safety-net
                     asyncio.Task that flushes whatever remains.

DB write order per flush:
  1. _ensure_creature_registered  — upsert creatures + creature_states
  2. _flush_buffer                — semantic summary + embedding → INSERT perception_snapshots
  3. _enforce_fifo_limit          — prune old rows (inline; already in background)
  4. _update_creature_states      — UPDATE creature_states from nested payload
  5. graph.ainvoke                — LangGraph AI reasoning
  6. _save_behavior_decision      — INSERT behavior_decisions (inline)
  7. persist_tick                 — serialise to agent_tick_history (inline)

All Supabase writes are best-effort: exceptions are caught, logged, and never
re-raised so Unity is never blocked by a DB or network hiccup.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid as _uuid_mod
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from fastapi import BackgroundTasks
from supabase import Client

from app.core.config import Settings
from app.core.logger import get_logger
from app.agent.creature_agent import CreatureAgent
from app.services.embedding_service import EmbeddingService
from app.services.memory_service import persist_tick, hydrate_agent, run_reflection_cycle
from app.services.semantic_service import SemanticService

logger = get_logger(__name__)

_STATUS_KEY    = "agent_status:{creature_id}"
_BUFFER_KEY    = "cat:buffer:{creature_id}"
_TIMER_DELAY_S = 120


class AgentServiceState:
    """
    Process-scoped state shared across all per-request AgentService instances.

    Holds per-creature asyncio.Locks (for Redis buffer serialisation) and the
    UUID of the most recently saved aggregated perception row.  Injected into
    AgentService so that state outlives the per-request DI lifecycle.
    """

    def __init__(self) -> None:
        # Per-creature locks — defaultdict creates a new Lock on first access.
        self.locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Most recent perception_snapshots.id for each creature.
        self.last_snapshot_ids: dict[str, str | None] = {}
        # How many times each creature's buffer has been flushed this session.
        self.flush_counts: dict[str, int] = {}


class AgentService:
    """
    Per-request orchestrator.  Receives all request-scoped dependencies via
    constructor injection.  Cross-request state (locks, last snapshot IDs)
    lives in the injected AgentServiceState singleton.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        settings: Settings,
        agent: CreatureAgent | None = None,
        graph: Any | None = None,
        supabase: Client | None = None,
        semantic_service: SemanticService | None = None,
        aggregation_limit: int = 10,
        state: AgentServiceState | None = None,
    ):
        # ── Per-request deps ────────────────────────────────────────────────
        self._redis             = redis
        self._settings          = settings
        self._ttl               = settings.agent_status_ttl
        self._agent             = agent
        self._graph             = graph
        self._supabase          = supabase
        self._aggregation_limit = aggregation_limit

        # SemanticService for narrative summaries; EmbeddingService for vectors.
        self._semantic   = semantic_service or SemanticService()
        self._embedding  = EmbeddingService(settings)

        # ── Shared state — outlives this request ────────────────────────────
        self._state = state or AgentServiceState()

        # ── Stable bound-method references (required for BackgroundTask `is`) ─
        self._enforce_fifo_limit = self._enforce_fifo_limit   # type: ignore[method-assign]
        self._run_flush_pipeline = self._run_flush_pipeline   # type: ignore[method-assign]

    # ── UUID helper ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_db_id(creature_id: str) -> str:
        """
        Return a valid UUID string for Supabase FK columns.

        If creature_id is already a well-formed UUID it is returned unchanged.
        Non-UUID identifiers (e.g. "default", "cat_1") are deterministically
        mapped to UUID v5 so the same logical creature always resolves to the
        same DB row across restarts.
        """
        try:
            _uuid_mod.UUID(creature_id)
            return creature_id
        except ValueError:
            return str(_uuid_mod.uuid5(_uuid_mod.NAMESPACE_DNS, creature_id))

    # ── Public API ───────────────────────────────────────────────────────────

    async def run_full_tick_flow(
        self,
        creature_id: str,
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """
        Redis-buffered tick pipeline with feature-toggle gating.

        Every tick: push payload to Redis LIST under cat:buffer:{creature_id}.

        ENABLE_MEMORY_PIPELINE=False (default):
          Return {"status": "buffering", "count": N} immediately.

        ENABLE_MEMORY_PIPELINE=True:
          Count trigger (LLEN >= aggregation_limit): pop all items, hand off
            to BackgroundTask _run_flush_pipeline, return {"status": "processing"}.
          Timer trigger (1st item pushed): spawn 120-second asyncio.Task that
            flushes any remaining items once the deadline passes.
        """
        db_id      = self._to_db_id(creature_id)
        redis_key  = _BUFFER_KEY.format(creature_id=creature_id)
        lock       = self._state.locks[creature_id]

        async with lock:
            await self._redis.rpush(redis_key, json.dumps(payload))
            current_len = await self._redis.llen(redis_key)

            if not self._settings.ENABLE_MEMORY_PIPELINE:
                logger.debug(
                    "Pipeline disabled — buffering creature=%s  %d items in Redis",
                    creature_id, current_len,
                )
                return {"status": "buffering", "count": current_len}

            # Timer trigger: first item entering an empty list.
            if current_len == 1:
                asyncio.create_task(
                    self._timer_flush(creature_id, db_id, redis_key),
                    name=f"timer_flush:{creature_id}",
                )
                logger.debug("Timer flush scheduled for creature=%s", creature_id)

            # Count trigger: aggregation window full.
            if current_len >= self._aggregation_limit:
                if self._graph is None or self._agent is None:
                    logger.warning(
                        "Count trigger fired but graph/agent unavailable for creature=%s"
                        " — items remain in Redis buffer",
                        creature_id,
                    )
                    return {"status": "buffering", "count": current_len}

                raw_items     = await self._redis.lrange(redis_key, 0, -1)
                await self._redis.delete(redis_key)
                snapshot_batch = [json.loads(item) for item in raw_items]

                background_tasks.add_task(
                    self._run_flush_pipeline,
                    creature_id,
                    db_id,
                    snapshot_batch,
                    payload,
                )
                logger.debug(
                    "Flush queued  creature=%s  db_id=%s  snapshots=%d",
                    creature_id, db_id, len(snapshot_batch),
                )
                return {"status": "processing"}

            return {"status": "buffering", "count": current_len}

    async def _timer_flush(
        self,
        creature_id: str,
        db_id: str,
        redis_key: str,
    ) -> None:
        """
        120-second safety-net flush.  Fires when the count trigger never
        reached the threshold (e.g. low-frequency ticks).

        Acquires the per-creature lock before touching Redis so it never
        races with a concurrent push or count-triggered flush.
        """
        await asyncio.sleep(_TIMER_DELAY_S)

        if self._graph is None or self._agent is None:
            logger.warning(
                "Timer flush: graph/agent unavailable for creature=%s — skipping",
                creature_id,
            )
            return

        lock = self._state.locks[creature_id]
        async with lock:
            raw_items = await self._redis.lrange(redis_key, 0, -1)
            if not raw_items:
                logger.debug("Timer flush: nothing to flush for creature=%s", creature_id)
                return
            await self._redis.delete(redis_key)

        snapshot_batch = [json.loads(item) for item in raw_items]
        logger.debug(
            "Timer flush executing  creature=%s  snapshots=%d",
            creature_id, len(snapshot_batch),
        )
        await self._run_flush_pipeline(
            creature_id, db_id, snapshot_batch, snapshot_batch[-1]
        )

    async def _run_flush_pipeline(
        self,
        creature_id: str,
        db_id: str,
        snapshot_batch: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> None:
        """
        Full flush pipeline — runs as a BackgroundTask (or direct await from
        _timer_flush) after the HTTP response has been sent to Unity.

        Steps:
          1. Ensure creature is registered in DB (FK prerequisite)
          2. Persist semantic summary + embedding → perception_snapshots
          3. Enforce FIFO row limit
          4. Sync creature_states from payload
          5. Run LangGraph AI reasoning
          6. Persist behavior_decision
          7. Persist tick history
        """
        try:
            # Step 1 — guarantee FK rows exist
            self._ensure_creature_registered(db_id, creature_id)

            # Step 2 — semantic summary + embedding → perception_snapshots INSERT
            if self._supabase is not None:
                snapshot_id = self._flush_buffer(db_id, snapshot_batch)
                self._state.last_snapshot_ids[creature_id] = snapshot_id
            else:
                logger.warning(
                    "Buffer full for creature %s but Supabase unavailable — "
                    "clearing without persist",
                    creature_id,
                )

            # Track how many times this creature has been flushed.
            flush_count = self._state.flush_counts.get(creature_id, 0) + 1
            self._state.flush_counts[creature_id] = flush_count
            logger.debug("Flush #%d for creature=%s", flush_count, creature_id)

            # Step 3 — FIFO enforcement (inline; already in background)
            if self._supabase is not None:
                self._enforce_fifo_limit(db_id)

            # Step 4 — sync Unity-pushed state values to creature_states
            self._update_creature_states(db_id, payload)

            # Step 5 — run the AI reasoning graph
            await self._set_status(creature_id, "thinking")
            try:
                await self._hydrate_if_empty(creature_id)
                result = await self._graph.ainvoke(
                    self._build_graph_input(creature_id, payload)
                )
            except Exception as exc:
                logger.error("AI reasoning failed: %s", exc)
                result = {
                    "tick":          self._agent.memory.tick_count,
                    "action_result": {
                        "action":   "wait",
                        "metadata": {"reason": "AI_SERVICE_UNAVAILABLE"},
                    },
                    "reasoning": f"Fallback: {exc}",
                }

            # Step 6 — persist behavior decision (inline; already in background)
            if self._supabase is not None:
                self._save_behavior_decision(
                    creature_id=db_id,
                    snapshot_id=self._state.last_snapshot_ids.get(creature_id),
                    result=result,
                )
                await persist_tick(
                    self._agent, self._supabase, self._redis, creature_id
                )

            # Step 7 — reflection cycle: condense recent snapshots → memory_summaries.
            #
            # Only runs when flush_count is a multiple of snapshot_limit (default 5),
            # i.e. once per full snapshot window rather than after every flush.
            # This avoids 5 concurrent LLM calls per creature which would:
            #   • block the async event loop via competing sync Supabase calls
            #   • push total flush latency to 60 s+ (LangGraph + reflection × 5)
            #   • hit the LLM timeout before the first meaningful summary is ready
            _REFLECTION_EVERY = 5  # run reflection every N flushes
            should_reflect = (
                self._supabase is not None
                and self._settings.ENABLE_REFLECTION_CYCLE
                and flush_count % _REFLECTION_EVERY == 0
            )
            if should_reflect:
                logger.info(
                    "Flush #%d: triggering reflection cycle for creature=%s",
                    flush_count, creature_id,
                )
                await run_reflection_cycle(
                    creature_id=creature_id,
                    supabase=self._supabase,
                    settings=self._settings,
                    snapshot_limit=_REFLECTION_EVERY,
                )

            await self._set_status(creature_id, "idle")

            action    = result.get("action_result") or {}
            reasoning = result.get("reasoning") or ""
            logger.info(
                "[FLUSH DONE] creature=%s  action=%s  metadata=%s\n"
                "             reasoning: %s",
                creature_id,
                action.get("action", "?"),
                action.get("metadata", {}),
                reasoning,
            )

        except Exception:
            logger.exception(
                "Flush pipeline failed for creature=%s — status reset to idle",
                creature_id,
            )
            await self._set_status(creature_id, "idle")

    async def run_tick(
        self,
        creature_id: str,
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Back-compat shim for AgentWorker."""
        return await self.run_full_tick_flow(creature_id, payload, background_tasks)

    async def get_status(self, creature_id: str) -> str:
        """Read creature status from Redis.  Returns 'idle' on cache miss."""
        value = await self._redis.get(_STATUS_KEY.format(creature_id=creature_id))
        if not value:
            return "idle"
        return value.decode() if isinstance(value, bytes) else value

    # ── Buffer Management ────────────────────────────────────────────────────

    def _flush_buffer(
        self, creature_id: str, snapshots: list[dict[str, Any]]
    ) -> str | None:
        """
        Generate a semantic summary (with spatio-temporal context) and a
        vector embedding for `snapshots`, then persist ONE row to
        perception_snapshots.  Returns the new row's UUID, or None on failure.

        Failure modes logged explicitly:
          - SemanticService raises (summary generation error)
          - EmbeddingService raises (embedding generation error — non-fatal,
            row is still persisted with embedding=NULL)
          - Supabase insert raises (FK violation, column mismatch, network)
          - Supabase insert succeeds but returns empty data (RLS rejection)
        """
        if self._supabase is None:
            return None

        last = snapshots[-1]
        loc  = last.get("self", {}).get("location", {})
        ts   = datetime.now(timezone.utc).isoformat()

        try:
            summary = self._semantic.generate_summary(
                snapshots, location=loc, timestamp=ts
            )
        except Exception:
            logger.exception(
                "SemanticService.generate_summary failed for creature=%s", creature_id
            )
            return None

        # Generate embedding — non-fatal if it fails.
        embedding: list[float] | None = None
        try:
            embedding = self._embedding.embed_text(summary) or None
        except Exception:
            logger.warning(
                "Embedding generation failed for creature=%s — "
                "storing perception_snapshot without embedding",
                creature_id,
            )

        row: dict[str, Any] = {
            "creature_id":  creature_id,
            "request_id":   last.get("requestId", ""),
            "summary_text": summary,
            "raw_payloads": snapshots,
            "pos_x":        loc.get("x", 0.0),
            "pos_y":        loc.get("y", 0.0),
            "pos_z":        loc.get("z", 0.0),
            "embedding":    embedding,
        }

        logger.debug(
            "Inserting perception_snapshot: creature=%s  summary_len=%d  "
            "has_embedding=%s  entities_in_last_tick=%d",
            creature_id, len(summary), embedding is not None,
            len(last.get("entities", [])),
        )

        try:
            _t0  = time.perf_counter()
            resp = self._supabase.table("perception_snapshots").insert(row).execute()
            _ms  = (time.perf_counter() - _t0) * 1000
        except Exception:
            logger.exception(
                "perception_snapshots INSERT raised — creature=%s  "
                "Likely cause: FK violation (creature not registered) or "
                "column schema mismatch.",
                creature_id,
            )
            return None

        if not resp.data:
            logger.error(
                "perception_snapshots INSERT returned no data for creature=%s. "
                "Possible causes: Supabase RLS policy blocked the write, or the "
                "response was empty despite no exception. "
                "Row attempted: creature_id=%s  request_id=%s  summary_text=%r",
                creature_id, creature_id,
                row["request_id"], summary[:120],
            )
            return None

        new_id = resp.data[0].get("id")
        logger.info(
            "[DB WRITE] perception_snapshots INSERT %.1f ms — "
            "id=%s  creature=%s  snapshots=%d  embedding=%s  summary=%r",
            _ms, new_id, creature_id, len(snapshots),
            "yes" if embedding else "no",
            summary[:80],
        )
        return new_id

    def _enforce_fifo_limit(self, creature_id: str, limit: int = 100) -> None:
        """
        Delete the oldest rows so the creature never exceeds `limit` aggregated
        snapshots.  Called inline inside _run_flush_pipeline (already in bg).
        """
        if self._supabase is None:
            return
        try:
            resp = (
                self._supabase.table("perception_snapshots")
                .select("id")
                .eq("creature_id", creature_id)
                .order("created_at", desc=False)
                .execute()
            )
            all_ids = [row["id"] for row in (resp.data or [])]
            excess  = len(all_ids) - limit
            if excess <= 0:
                return
            ids_to_delete = all_ids[:excess]
            self._supabase.table("perception_snapshots").delete().in_(
                "id", ids_to_delete
            ).execute()
            logger.info(
                "FIFO: pruned %d old snapshot(s) for creature %s", excess, creature_id
            )
        except Exception:
            logger.exception("FIFO enforcement failed for creature %s", creature_id)

    # ── Private: DB helpers ──────────────────────────────────────────────────

    def _ensure_creature_registered(self, db_id: str, alias: str) -> None:
        """
        Guarantee a creatures row + creature_states row exist before any FK
        write to perception_snapshots or behavior_decisions.

        Args:
            db_id:  UUID string (from _to_db_id) used as the PK in every table.
            alias:  Original human-readable creature_id (e.g. "cat_anxious")
                    stored in creatures.name so the row is identifiable in the DB.
        """
        if self._supabase is None:
            return

        try:
            resp = (
                self._supabase.table("creature_states")
                .select("creature_id")
                .eq("creature_id", db_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                return  # already registered — nothing to do

            logger.info(
                "Auto-registering new creature: alias=%r  db_id=%s", alias, db_id
            )

            now_iso = datetime.now(timezone.utc).isoformat()

            creature_resp = self._supabase.table("creatures").upsert(
                {
                    "id":         db_id,
                    "species":    "cat",
                    "name":       alias,
                    "created_at": now_iso,
                },
                on_conflict="id",
            ).execute()

            if not creature_resp.data:
                logger.error(
                    "creatures upsert returned no data — possible RLS or schema "
                    "mismatch.  alias=%r  db_id=%s", alias, db_id
                )
            else:
                logger.info("creatures upsert OK: %s", creature_resp.data)

            states_resp = self._supabase.table("creature_states").upsert(
                {
                    "creature_id": db_id,
                    "hunger":    0.0,
                    "energy":    1.0,
                    "mood":      0.0,
                    "curiosity": 0.5,
                    "fear":      0.0,
                },
                on_conflict="creature_id",
            ).execute()

            if not states_resp.data:
                logger.error(
                    "creature_states upsert returned no data — possible RLS or "
                    "FK violation.  alias=%r  db_id=%s", alias, db_id
                )
            else:
                logger.info("creature_states upsert OK: %s", states_resp.data)

        except Exception:
            logger.exception(
                "Failed to register creature alias=%r db_id=%s — "
                "subsequent FK writes will fail",
                alias, db_id,
            )
            raise

    def _update_creature_states(
        self, creature_id: str, payload: dict[str, Any]
    ) -> None:
        """Sync Unity-pushed values from the nested payload to creature_states."""
        if self._supabase is None:
            return
        mood   = payload.get("mood",   {})
        health = payload.get("health", {})
        patch: dict[str, Any] = {}
        if "hunger"    in health: patch["hunger"]    = health["hunger"]
        if "energy"    in mood:   patch["energy"]    = mood["energy"]
        if "fear"      in mood:   patch["fear"]      = mood["fear"]
        if "curiosity" in mood:   patch["curiosity"] = mood["curiosity"]
        if "trust" in mood and "fear" in mood:
            patch["mood"] = round(mood["trust"] - mood["fear"], 4)
        if not patch:
            return
        try:
            patch["updated_at"] = datetime.now(timezone.utc).isoformat()
            _t0 = time.perf_counter()
            self._supabase.table("creature_states").update(patch).eq(
                "creature_id", creature_id
            ).execute()
            _ms = (time.perf_counter() - _t0) * 1000
            logger.info(
                "[DB WRITE] creature_states UPDATE %.1f ms — creature=%s  fields=%s",
                _ms, creature_id, sorted(k for k in patch if k != "updated_at"),
            )
        except Exception:
            logger.exception("Failed to update creature_states for %s", creature_id)

    def _save_behavior_decision(
        self,
        creature_id: str,
        snapshot_id: str | None,
        result: dict[str, Any],
    ) -> None:
        """INSERT a behavior_decisions row.  Called inline inside _run_flush_pipeline."""
        if self._supabase is None:
            return
        try:
            action = result.get("action_result") or {}
            _SKIP = {"messages", "raw_payload"}
            raw_output = {k: v for k, v in result.items() if k not in _SKIP}
            row = {
                "creature_id":      creature_id,
                "snapshot_id":      snapshot_id,
                "decision_type":    action.get("action", "idle"),
                "reasoning":        result.get("reasoning"),
                "raw_brain_output": raw_output,
                "status":           "completed",
            }
            _t0 = time.perf_counter()
            self._supabase.table("behavior_decisions").insert(row).execute()
            _ms = (time.perf_counter() - _t0) * 1000
            logger.info(
                "[DB WRITE] behavior_decisions INSERT %.1f ms — "
                "creature=%s  decision=%s",
                _ms, creature_id, action.get("action", "idle"),
            )
        except Exception:
            logger.exception(
                "Failed to save behavior_decision for creature %s", creature_id
            )

    async def _hydrate_if_empty(self, creature_id: str) -> None:
        """Restore agent memory from DB/cache before the first tick of a session."""
        if self._agent.memory.tick_count > 0:
            return
        if self._supabase is None:
            return
        await hydrate_agent(
            self._agent, self._supabase, self._redis, creature_id=creature_id
        )

    async def _set_status(self, creature_id: str, status: str) -> None:
        """Write creature status to Redis.  Swallows connection errors silently."""
        try:
            await self._redis.set(
                _STATUS_KEY.format(creature_id=creature_id), status, ex=self._ttl
            )
        except Exception as exc:
            logger.warning("Redis status update skipped: %s", exc)

    def _build_graph_input(
        self, creature_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Normalise the nested Unity payload to the flat dict the LangGraph nodes
        expect.  Keeps the graph decoupled from schema changes in Unity.
        """
        mood   = payload.get("mood",   {})
        health = payload.get("health", {})
        loc    = payload.get("self",   {}).get("location", {})
        return {
            "creature_id":       creature_id,
            "raw_payload":       payload,
            "messages":          [],
            "tick":              self._agent.memory.tick_count,
            "available_actions": self._agent.body.available_actions,
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "pos_x":     loc.get("x", 0.0),
            "pos_y":     loc.get("y", 0.0),
            "pos_z":     loc.get("z", 0.0),
            "hunger":    health.get("hunger",    0.0),
            "energy":    mood.get("energy",      1.0),
            "fear":      mood.get("fear",        0.0),
            "curiosity": mood.get("curiosity",   0.5),
            "mood":      round(mood.get("trust", 0.0) - mood.get("fear", 0.0), 4),
        }
