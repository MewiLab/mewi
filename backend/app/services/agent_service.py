"""
AgentService — orchestrates one tick of the agent loop.

Two public methods, two callers:
  run_tick()   ← POST /agent/tick  (Unity hot path)
  get_status() ← GET  /agent/status/{id}  (frontend polling)

Status lifecycle lives here, not in the router.
The router is only responsible for HTTP parsing and response shaping.

Why not keep this logic in the router?
  - Routers are untestable as units (they require the full FastAPI stack)
  - Status bookkeeping + graph call + persistence is orchestration, not HTTP
  - A future worker/queue can call run_tick() without touching the router at all
"""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis
from fastapi import BackgroundTasks
from supabase import Client

from app.core.config import Settings
from app.agent.creature_agent import CreatureAgent
from app.services.memory_service import persist_tick

logger = logging.getLogger(__name__)

# Redis key template — centralised so nothing else hardcodes it
_STATUS_KEY = "agent_status:{creature_id}"


class AgentService:
    """
    Orchestrates the agent tick loop and exposes status reads.

    Constructor takes all dependencies explicitly — no imports of
    app.state, no singletons. Fully injectable and testable.
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

    # for agent_router to call
    async def run_tick(
        self,
        creature_id: str,
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """
        Run one full agent tick: perceive → remember → reason → act → reflect.

        Manages the thinking/idle status transition around the graph call.
        Schedules persistence as a non-blocking background task.

        Returns the tick result dict for the router to shape into a response.

        Raises on graph failure after resetting status to idle — the router
        can catch and return a 500 without the creature being stuck "thinking".
        """
        if self._graph is None or self._agent is None:
            raise RuntimeError("AgentService.run_tick called without graph/agent — use the full constructor")

        await self._set_status(creature_id, "thinking")
        try:
            result = await self._graph.ainvoke({
                "raw_payload":    payload,
                "messages":       [],
                "tick":           self._agent.memory.tick_count,
                "available_actions": self._agent.body.available_actions,
                "perception":     None,
                "perception_error": None,
                "memory_context": None,
                "chosen_action":  None,
                "reasoning":      None,
                "action_result":  None,
            })
        except Exception:
            logger.exception("Graph failed for creature %s", creature_id)
            raise
        finally:
            # Always unblock Unity's animation system, even on failure
            await self._set_status(creature_id, "idle")

        # Non-blocking persistence — doesn't slow Unity's response
        if self._supabase is not None:
            background_tasks.add_task(
                persist_tick, self._agent, self._supabase, self._redis
            )

        return result

    async def get_status(self, creature_id: str) -> str:
        """
        Read the creature's current status from Redis.
        Returns "idle" if no key exists (TTL expired or first poll).
        """
        value = await self._redis.get(_STATUS_KEY.format(creature_id=creature_id))
        return value.decode() if value else "idle"

    async def _set_status(self, creature_id: str, status: str) -> None:
        """Write status to Redis with TTL. Private — callers use run_tick()."""
        await self._redis.set(
            _STATUS_KEY.format(creature_id=creature_id),
            status,
            ex=self._ttl,
        )