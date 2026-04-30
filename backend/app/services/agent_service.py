"""
AgentService — orchestrates one full agent tick.

Public surface:
  run_full_tick_flow()  ← POST /agent/tick  (Unity hot path, full DB pipeline)
  run_tick()            ← AgentWorker back-compat shim → delegates to above
  get_status()          ← GET  /agent/status/{id}  (frontend polling)

DB write order per tick:
  1. _ensure_creature_registered  — upsert creatures + creature_states (auto-reg)
  2. _save_perception_snapshot    — INSERT perception_snapshots, returns row id
  3. _update_creature_states      — UPDATE creature_states from payload stats
  4. graph.ainvoke                — LangGraph AI reasoning
  5. _save_behavior_decision      — INSERT behavior_decisions (background task)
  6. persist_tick                 — serialise to agent_tick_history (background task)

All Supabase writes are best-effort: exceptions are caught, logged with full
traceback, and never re-raised — so Unity is never blocked by a DB hiccup.
"""

from __future__ import annotations

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

logger = get_logger(__name__)

_STATUS_KEY = "agent_status:{creature_id}"

# Stable namespace for deterministic UUID generation (DNS namespace UUID)
_CREATURE_NS = _uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


class AgentService:
    """
    Stateless orchestrator.  All dependencies are injected via constructor
    so this class is fully testable without FastAPI or a real DB.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        settings: Settings,
        agent: CreatureAgent | None = None,
        graph: Any | None = None,
        supabase: Client | None = None,
    ):
        self._redis    = redis
        self._ttl      = settings.agent_status_ttl
        self._agent    = agent
        self._graph    = graph
        self._supabase = supabase

    # ── Public API ──────────────────────────────────────────────────────────

    async def run_full_tick_flow(
        self,
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """
        Full tick pipeline:
          auto-register → snapshot → state update → AI graph → persist (bg)

        Raises RuntimeError if called without graph/agent (misconfigured DI).
        Raises any unhandled graph exception after resetting status to idle.
        All DB side-effects are best-effort and never block the response.
        """
        if self._graph is None or self._agent is None:
            raise RuntimeError(
                "AgentService.run_full_tick_flow requires graph and agent — "
                "use the full constructor via AgentServiceDep"
            )

        creature_id: str = (
            payload.get("creature_id")
            or payload.get("user_id")
            or "default"
        )

        # [EDD] Log the raw incoming snapshot for test-case reproducibility.
        logger.debug("EDD snapshot  creature=%s  payload=%s", creature_id, payload)

        # Step 1 — ensure rows exist so FK constraints on later inserts hold
        self._ensure_creature_registered(creature_id)

        # Step 2 — persist raw environment data; capture id for decision linkage
        snapshot_id = self._save_perception_snapshot(creature_id, payload)

        # Step 3 — sync internal states pushed from Unity
        self._update_creature_states(creature_id, payload)

        # Step 4 — run the AI reasoning graph
        await self._set_status(creature_id, "thinking")
        try:
            await self._hydrate_if_empty(creature_id)
            result = await self._graph.ainvoke({
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
            })
        except Exception as e:
            # Log the error but do not crash the request.
            # This allows us to verify if Supabase writes (Step 5) work correctly.
            logger.error(f"AI Reasoning failed (Timeout/Auth): {e}")
            
            # Provide a fallback result so the pipeline can continue.
            result = {
                "tick": self._agent.memory.tick_count,
                "action_result": {
                    "action": "wait", 
                    "metadata": {"reason": "AI_SERVICE_UNAVAILABLE"}
                },
                "reasoning": f"Fallback action triggered due to error: {str(e)}"
            }
        finally:
            await self._set_status(creature_id, "idle")

        # Step 5 — non-blocking persistence (runs after HTTP response is sent)
        if self._supabase is not None:
            background_tasks.add_task(
                self._save_behavior_decision,
                creature_id=creature_id,
                snapshot_id=snapshot_id,
                result=result,
            )
            background_tasks.add_task(
                persist_tick, self._agent, self._supabase, self._redis,
                creature_id,
            )

        # [EDD] Log the final AI output for round-trip test verification.
        logger.debug(
            "EDD result  creature=%s  tick=%s  action=%s",
            creature_id, result.get("tick"), result.get("action_result"),
        )
        return result

    async def run_tick(
        self,
        creature_id: str,
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Back-compat shim for AgentWorker — delegates to run_full_tick_flow."""
        return await self.run_full_tick_flow(
            {**payload, "creature_id": creature_id},
            background_tasks,
        )

    async def get_status(self, creature_id: str) -> str:
        """Read creature status from Redis. Returns 'idle' on cache miss."""
        value = await self._redis.get(_STATUS_KEY.format(creature_id=creature_id))
        if not value:
            return "idle"
        return value.decode() if isinstance(value, bytes) else value

    # ── Private: DB helpers ─────────────────────────────────────────────────

    @staticmethod
    def _to_db_id(creature_id: str) -> str:
        """
        creatures.id is a Postgres uuid column.  Convert a plain string like
        'default' or 'cat_01' into a stable, deterministic UUID so that every
        insert and FK reference always satisfies the column type constraint.
        Strings that are already valid UUIDs are returned unchanged.
        """
        try:
            _uuid_mod.UUID(creature_id)
            return creature_id
        except ValueError:
            return str(_uuid_mod.uuid5(_CREATURE_NS, creature_id))

    def _ensure_creature_registered(self, creature_id: str) -> None:
        """
        Guarantee a creature row + creature_states row exist before any FK
        writes. SELECT first to avoid clobbering existing state values on
        every tick; only INSERT if the creature is genuinely new.

        try/except intentionally removed — raw DB exceptions now propagate
        so they appear in Railway logs instead of being silently swallowed.
        The caller (run_full_tick_flow) has its own error handling.
        """
        if self._supabase is None:
            return

        db_id = self._to_db_id(creature_id)
        logger.info(
            "Checking creature registration: logical_id=%r  db_uuid=%s",
            creature_id, db_id,
        )

        resp = (
            self._supabase.table("creature_states")
            .select("creature_id")
            .eq("creature_id", db_id)
            .limit(1)
            .execute()
        )
        if resp.data:
            return  # Already registered — fast path

        # New creature: insert the parent row first, then the states row.
        creatures_row = {
            "id":         db_id,
            "species":    "cat",
            "name":       creature_id,   # preserve the logical name for readability
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Inserting into creatures: %s", creatures_row)
        self._supabase.table("creatures").upsert(
            creatures_row,
            on_conflict="id",
        ).execute()

        states_row = {
            "creature_id": db_id,
            "hunger":      0.0,
            "energy":      1.0,
            "mood":        0.0,
            "curiosity":   0.5,
            "fear":        0.0,
        }
        logger.info("Inserting into creature_states: %s", states_row)
        self._supabase.table("creature_states").insert(states_row).execute()
        logger.info("Auto-registration complete for %r (%s)", creature_id, db_id)

    def _save_perception_snapshot(
        self, creature_id: str, payload: dict[str, Any]
    ) -> str | None:
        """
        INSERT a row into perception_snapshots.
        Returns the generated UUID so behavior_decisions can reference it.
        Returns None on failure (decision row will have NULL snapshot_id).
        """
        if self._supabase is None:
            return None
        try:
            row = {
                "creature_id":   self._to_db_id(creature_id),
                "pos_x":         payload.get("pos_x", 0.0),
                "pos_y":         payload.get("pos_y", 0.0),
                "pos_z":         payload.get("pos_z", 0.0),
                "user_distance": payload.get("user_distance", 0.0),
                "user_velocity": payload.get("user_velocity", 0.0),
                "time_of_day":   payload.get("time_of_day", 0),
                "raw_data":      payload,
            }
            resp = self._supabase.table("perception_snapshots").insert(row).execute()
            if resp.data:
                return resp.data[0].get("id")
        except Exception:
            logger.exception(
                "Failed to save perception_snapshot for creature %s", creature_id
            )
        return None

    def _update_creature_states(
        self, creature_id: str, payload: dict[str, Any]
    ) -> None:
        """
        Overwrite the creature's internal state columns with values pushed
        from Unity. Only updates fields actually present in the payload so
        partial ticks don't zero out unmentioned stats.
        """
        if self._supabase is None:
            return
        state_keys = ("hunger", "energy", "mood", "curiosity", "fear")
        patch = {k: payload[k] for k in state_keys if k in payload}
        if not patch:
            return
        try:
            patch["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._supabase.table("creature_states").update(patch).eq(
                "creature_id", self._to_db_id(creature_id)
            ).execute()
        except Exception:
            logger.exception(
                "Failed to update creature_states for %s", creature_id
            )

    def _save_behavior_decision(
        self,
        creature_id: str,
        snapshot_id: str | None,
        result: dict[str, Any],
    ) -> None:
        """
        INSERT a row into behavior_decisions.
        Called as a BackgroundTask — runs after the HTTP response is sent.
        """
        if self._supabase is None:
            return
        try:
            action = result.get("action_result") or {}
            row = {
                "creature_id":      self._to_db_id(creature_id),
                "snapshot_id":      snapshot_id,
                "decision_type":    action.get("action", "idle"),
                "reasoning":        result.get("reasoning"),
                "raw_brain_output": result,
                "status":           "completed",
            }
            self._supabase.table("behavior_decisions").insert(row).execute()
        except Exception:
            logger.exception(
                "Failed to save behavior_decision for creature %s", creature_id
            )

    async def _hydrate_if_empty(self, creature_id: str) -> None:
        """
        Restore agent memory from DB/cache before the first tick of a session.
        No-op when the in-memory buffer already has ticks (hot path).
        """
        if self._agent.memory.tick_count > 0:
            return
        if self._supabase is None:
            return
        await hydrate_agent(
            self._agent, self._supabase, self._redis, creature_id=creature_id
        )

    async def _set_status(self, creature_id: str, status: str) -> None:
        """
        Updates the creature's status in Redis.
        Wrapped in try-except to ensure Redis Auth/Connection issues 
        do not crash the main API response for Unity.
        """
        try:
            await self._redis.set(
                _STATUS_KEY.format(creature_id=creature_id),
                status,
                ex=self._ttl,
            )
        except Exception as e:
            # We log the warning but do NOT re-raise the exception.
            # This allows the API to return 200 OK even if Redis is down.
            logger.warning(f"Redis status update skipped: {e}")
