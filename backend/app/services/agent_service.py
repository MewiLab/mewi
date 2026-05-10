"""
AgentService — orchestrates one full agent tick with semantic aggregation.

Architecture: per-request instance + shared state
  get_agent_service (deps.py) creates a fresh AgentService on every request,
  injecting request-scoped deps (redis, supabase, agent, graph) cleanly.
  Persistent cross-request data lives in AgentServiceState, which is a
  process-scoped singleton injected at construction time.

Buffer strategy (X-to-1 compression):
  Raw Unity snapshots accumulate in AgentServiceState.buffers, keyed by
  creature_id.  When the buffer reaches `aggregation_limit`, SemanticService
  condenses all snapshots into one narrative string that is persisted as a
  single row in perception_snapshots.  FIFO enforcement keeps each creature
  at ≤ 100 rows.

DB write order per tick:
  1. _ensure_creature_registered  — upsert creatures + creature_states
  2. Append to in-memory buffer   — zero DB cost on most ticks
  3. [buffer full, supabase set]  — _flush_buffer → INSERT perception_snapshots
  4. [buffer full, supabase set]  — _enforce_fifo (BackgroundTask)
  5. _update_creature_states      — UPDATE creature_states from nested payload
  6. graph.ainvoke                — LangGraph AI reasoning
  7. _save_behavior_decision      — INSERT behavior_decisions (BackgroundTask)
  8. persist_tick                 — serialise to agent_tick_history (BackgroundTask)

All Supabase writes are best-effort: exceptions are caught, logged, and never
re-raised so Unity is never blocked by a DB or network hiccup.

Thread safety:
  AgentServiceState dicts are mutated concurrently under CPython's GIL, which
  makes individual dict read/write operations atomic.  This is safe for
  single-process deployments.  A multi-process deployment would need an
  external store (e.g. Redis) for the shared buffers.
"""

from __future__ import annotations

import time
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from fastapi import BackgroundTasks
from supabase import Client

from app.core.config import Settings
from app.core.logger import get_logger
from app.agent.creature_agent import CreatureAgent
from app.services.memory_service import persist_tick, hydrate_agent
from app.services.semantic_service import SemanticService

logger = get_logger(__name__)

_STATUS_KEY = "agent_status:{creature_id}"


class AgentServiceState:
    """
    Process-scoped state shared across all per-request AgentService instances.

    Holds per-creature snapshot buffers and the UUID of the most recently
    saved aggregated perception row.  Injected into AgentService so that
    buffer contents survive the per-request dependency-injection lifecycle.
    """

    def __init__(self) -> None:
        # Snapshot windows keyed by creature_id.
        self.buffers: dict[str, list[dict[str, Any]]] = {}
        # Most recent perception_snapshots.id for each creature.
        # Used as snapshot_id FK in behavior_decisions rows.
        self.last_snapshot_ids: dict[str, str | None] = {}


class AgentService:
    """
    Per-request orchestrator.  Receives all request-scoped dependencies via
    constructor injection.  Cross-request state (buffers, last snapshot IDs)
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
        # ── Per-request deps (safe to overwrite — each request gets its own instance) ──
        self._redis             = redis
        self._ttl               = settings.agent_status_ttl
        self._agent             = agent
        self._graph             = graph
        self._supabase          = supabase
        self._semantic          = semantic_service or SemanticService()
        self._aggregation_limit = aggregation_limit

        # ── Shared state — outlives this request ──────────────────────────────
        # Fall back to a fresh state when none is injected (unit-test path).
        # In production, deps.py injects the process-level singleton so all
        # concurrent instances share the same buffers.
        self._state = state or AgentServiceState()

        # Expose shared collections as direct attributes so call sites and test
        # assertions use the same `svc.buffers` / `svc._last_snapshot_ids` names
        # as before.  These are *references* to the same dict objects held inside
        # self._state, so any mutation is immediately visible to every other
        # AgentService instance sharing the same state.
        self.buffers            = self._state.buffers
        self._last_snapshot_ids = self._state.last_snapshot_ids

        # ── Stable bound-method reference ────────────────────────────────────
        # Python creates a new wrapper object on every descriptor access, making
        # `self.m is self.m` normally False.  Storing here as an instance
        # attribute pins the identity so BackgroundTask assertions can use `is`.
        self._enforce_fifo_limit = self._enforce_fifo_limit  # type: ignore[method-assign]

    # ── UUID helper ─────────────────────────────────────────────────────────

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

    # ── Public API ──────────────────────────────────────────────────────────

    async def run_full_tick_flow(
        self,
        creature_id: str,
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """
        10-to-1 aggregation tick pipeline.

        Ticks 1-9: append to in-memory buffer, return immediately with
          {"status": "buffering", "count": N} — zero LLM / DB cost.

        Tick 10 (flush): semantic summary → perception_snapshots INSERT →
          LangGraph reasoning → behavior_decisions INSERT (background).

        Raises RuntimeError when graph/agent are absent (misconfigured DI).
        _to_db_id() ensures every FK value is a valid UUID regardless of
        what string Unity sends as creature_id.
        """
        if self._graph is None or self._agent is None:
            raise RuntimeError(
                "AgentService.run_full_tick_flow requires graph and agent — "
                "use the full constructor via AgentServiceDep"
            )

        # Resolve a stable UUID for every Supabase FK column.
        db_id = self._to_db_id(creature_id)

        # ── Step 1: append to in-memory buffer (zero DB / LLM cost) ──────────
        buffer = self.buffers.setdefault(creature_id, [])
        buffer.append(payload)
        count = len(buffer)

        # ── Step 2: early return while the aggregation window is filling ──────
        if count < self._aggregation_limit:
            logger.debug(
                "Buffering  creature=%s  %d/%d",
                creature_id, count, self._aggregation_limit,
            )
            return {"status": "buffering", "count": count}

        # ── Flush tick: buffer has reached the aggregation limit ──────────────

        # Step 3 — guarantee FK rows exist before any INSERT
        # Pass both the stable UUID (db_id) and the original alias (creature_id)
        # so the creatures.name column stores the human-readable identifier.
        self._ensure_creature_registered(db_id, creature_id)

        # Step 4 — copy & clear buffer; persist semantic summary + raw payloads
        snapshot_batch = buffer.copy()
        buffer.clear()

        if self._supabase is not None:
            snapshot_id = self._flush_buffer(db_id, snapshot_batch)
            self._last_snapshot_ids[creature_id] = snapshot_id
            background_tasks.add_task(self._enforce_fifo_limit, db_id)
        else:
            logger.warning(
                "Buffer full for creature %s but Supabase unavailable — "
                "clearing without persist",
                creature_id,
            )

        # Step 5 — sync Unity-pushed state values to creature_states
        self._update_creature_states(db_id, payload)

        # Step 6 — run the AI reasoning graph (last payload as representative)
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
        finally:
            await self._set_status(creature_id, "idle")

        # Step 7 — non-blocking persistence (runs after HTTP response is sent)
        if self._supabase is not None:
            background_tasks.add_task(
                self._save_behavior_decision,
                creature_id=db_id,
                snapshot_id=self._last_snapshot_ids.get(creature_id),
                result=result,
            )
            background_tasks.add_task(
                persist_tick, self._agent, self._supabase, self._redis, creature_id,
            )

        logger.debug(
            "Flush  creature=%s  db_id=%s  tick=%s  action=%s",
            creature_id, db_id, result.get("tick"), result.get("action_result"),
        )
        return result

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

    # ── Buffer Management ───────────────────────────────────────────────────

    def _flush_buffer(
        self, creature_id: str, snapshots: list[dict[str, Any]]
    ) -> str | None:
        """
        Generate a semantic summary for `snapshots` and persist ONE row to
        perception_snapshots.  Returns the new row's UUID, or None on failure.

        Failure modes logged explicitly:
          - SemanticService raises (summary generation error)
          - Supabase insert raises (FK violation, column mismatch, network)
          - Supabase insert succeeds but returns empty data (RLS silent rejection)
        """
        if self._supabase is None:
            return None

        try:
            summary = self._semantic.generate_summary(snapshots)
        except Exception:
            logger.exception(
                "SemanticService.generate_summary failed for creature=%s", creature_id
            )
            return None

        last = snapshots[-1]
        loc  = last.get("self", {}).get("location", {})
        row  = {
            "creature_id":  creature_id,
            "request_id":   last.get("requestId", ""),
            "summary_text": summary,
            "raw_payloads": snapshots,
            "pos_x":        loc.get("x", 0.0),
            "pos_y":        loc.get("y", 0.0),
            "pos_z":        loc.get("z", 0.0),
        }

        logger.debug(
            "Inserting perception_snapshot: creature=%s  summary_len=%d  "
            "entities_in_last_tick=%d",
            creature_id, len(summary), len(last.get("entities", [])),
        )

        try:
            _t0 = time.perf_counter()
            resp = self._supabase.table("perception_snapshots").insert(row).execute()
            _ms = (time.perf_counter() - _t0) * 1000
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
            "id=%s  creature=%s  snapshots=%d  summary=%r",
            _ms, new_id, creature_id, len(snapshots), summary[:80],
        )
        return new_id

    def _enforce_fifo_limit(self, creature_id: str, limit: int = 100) -> None:
        """
        Delete the oldest rows so the creature never exceeds `limit` aggregated
        snapshots.  Runs as a BackgroundTask — safe to fail silently.
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

    # ── Private: DB helpers ─────────────────────────────────────────────────

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
                    "id":         db_id,    # stable UUID derived from alias
                    "species":    "cat",
                    "name":       alias,    # human-readable alias stored for reference
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
            raise  # re-raise so the caller (run_full_tick_flow) surfaces a 503

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
        """INSERT a behavior_decisions row.  Called as a BackgroundTask."""
        if self._supabase is None:
            return
        try:
            action = result.get("action_result") or {}
            row = {
                "creature_id":      creature_id,
                "snapshot_id":      snapshot_id,
                "decision_type":    action.get("action", "idle"),
                "reasoning":        result.get("reasoning"),
                "raw_brain_output": result,
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
            # Flat fields for graph nodes that pre-date the nested schema
            "pos_x":     loc.get("x", 0.0),
            "pos_y":     loc.get("y", 0.0),
            "pos_z":     loc.get("z", 0.0),
            "hunger":    health.get("hunger",    0.0),
            "energy":    mood.get("energy",      1.0),
            "fear":      mood.get("fear",        0.0),
            "curiosity": mood.get("curiosity",   0.5),
            "mood":      round(mood.get("trust", 0.0) - mood.get("fear", 0.0), 4),
        }
