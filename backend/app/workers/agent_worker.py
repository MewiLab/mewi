"""
Background worker: agent "thinking" pipeline.

Two things live here:

  run_agent_job()
      Called as a FastAPI BackgroundTask from agent_router.py.
      Invokes the LangGraph for one Unity-triggered tick and stores the result.

  AgentWorker
      Autonomous periodic worker (extends BaseWorker).
      Runs a self-directed tick on every interval even when Unity hasn't
      sent a snapshot — keeps MEW "alive" between explicit requests.
"""

import asyncio
import logging
import uuid

import redis.asyncio as aioredis
from supabase import Client

from app.core.config import Settings
from app.workers.base import BaseWorker
from app.agent.creature_agent import CreatureAgent
from app.services.agent_service import AgentService
from app.services.memory_service import log_contextual_decision
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)


# ── Per-request job ───────────────────────────────────────────────────────────

async def run_agent_job(
    *,
    job_id: str,
    payload: dict,
    redis: aioredis.Redis,
    settings: Settings,
    graph,
    agent: CreatureAgent,
    supabase=None,
) -> None:
    """
    Run one LangGraph tick and store the result via AgentService for Unity to poll.

    After the graph finishes, fires a background task to log the decision to
    the micrologs table (Contextual Retrieval format) without blocking Unity.

    Job lifecycle (managed by AgentService):
      "pending"            — set by the router before this task starts
      {"status":"done",…}  — written here on success
      {"status":"error"}   — written here on failure; Unity aborts polling
    """
    svc = AgentService(redis, settings)

    try:
        result = await graph.ainvoke({
            "raw_payload":       payload,
            "messages":          [],
            "tick":              agent.memory.tick_count,
            "available_actions": agent.body.available_actions,
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "goal":              None,
            "internal_state":    None,
        })

        action_result = result.get("action_result") or {}
        kwargs        = action_result.get("kwargs") or {}

        await svc.complete_job(job_id, {
            "action":    action_result.get("action", "wait"),
            "x":         float(kwargs.get("x", 0.0)),
            "y":         float(kwargs.get("y", 0.0)),
            "z":         float(kwargs.get("z", 0.0)),
            "target":    str(kwargs.get("target", "")),
            "reasoning": result.get("reasoning", ""),
        })

        # Fire-and-forget: log the decision with situational context.
        if supabase is not None:
            asyncio.create_task(
                log_contextual_decision(
                    action=action_result.get("action", "wait"),
                    reasoning=result.get("reasoning", ""),
                    perception_ctx=result.get("perception") or {},
                    supabase=supabase,
                )
            )

    except Exception:
        logger.exception("Agent job %s failed", job_id)
        await svc.fail_job(job_id)


# ── Autonomous background worker ──────────────────────────────────────────────

class AgentWorker(BaseWorker):
    """
    Self-directed tick loop for the creature.

    On each interval it asks Unity for the current world state, constructs a
    synthetic snapshot, invokes the graph, and persists the result via Redis.
    This keeps MEW "thinking" even when Unity hasn't explicitly POSTed /tick.

    Errors in a single tick are isolated — the worker never stops running.
    """

    name = "agent_worker"

    def __init__(
        self,
        *,
        creature_id: str,
        agent: CreatureAgent,
        graph,
        redis: aioredis.Redis,
        supabase,
        settings: Settings,
        interval_seconds: float,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds)
        self._creature_id = creature_id
        self._agent       = agent
        self._graph       = graph
        self._redis       = redis
        self._supabase    = supabase
        self._settings    = settings

    async def _run_once(self) -> None:
        """
        Perform one autonomous agent tick.

        Attempts to fetch the current Unity world state.  If Unity is not
        reachable the tick is skipped silently — the worker picks up again
        on the next interval.
        """
        if not self._agent.body.is_connected:
            self._log.debug("Unity not connected — skipping autonomous tick")
            return

        try:
            state_data = await self._agent.body.get_state()
            world_data = await self._agent.body.get_world()
        except Exception:
            self._log.debug("Could not reach Unity for autonomous tick", exc_info=True)
            return

        # Build a minimal synthetic snapshot from Unity query results.
        # Real production code may have a richer /snapshot endpoint.
        payload = _build_payload_from_state(state_data, world_data)

        job_id = uuid.uuid4().hex[:8]
        svc    = AgentService(self._redis, self._settings)
        await svc.enqueue_job(job_id)

        await run_agent_job(
            job_id=job_id,
            payload=payload,
            redis=self._redis,
            settings=self._settings,
            graph=self._graph,
            agent=self._agent,
            supabase=self._supabase,
        )


def _build_payload_from_state(state: dict, world: dict) -> dict:
    """
    Assemble a perception payload from Unity's /state and /world query results.

    This is a best-effort conversion — fields that Unity doesn't provide
    fall back to safe defaults so the schema always validates.
    """
    return {
        "creature_snapshot": {
            "position": {
                "x": float(state.get("posX", 0.0)),
                "y": float(state.get("posY", 0.0)),
                "z": float(state.get("posZ", 0.0)),
            },
            "rotation_y":    float(state.get("rotY", 0.0)),
            "active_state":  str(state.get("state", "Idle")),
            "active_stance": str(state.get("stance", "Default")),
            "grounded":      bool(state.get("grounded", True)),
            "speed":         float(state.get("speed", 0.0)),
            "sprint":        bool(state.get("sprint", False)),
        },
        "environment_snapshot": {
            "time_of_day": float(state.get("timeOfDay", 12.0)),
            "weather":     str(state.get("weather", "clear")),
            "entities":    world.get("objects", []),
        },
    }
