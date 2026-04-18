"""
Background worker: agent "thinking" pipeline.

Runs as a FastAPI BackgroundTask. All dependencies are passed explicitly
so the worker is testable in isolation.
"""

import logging

import redis.asyncio as aioredis

from app.agent.creature_agent import CreatureAgent
from app.core.config import Settings
from app.services.agent_service import AgentService

logger = logging.getLogger(__name__)


async def run_agent_job(
    *,
    job_id: str,
    payload: dict,
    redis: aioredis.Redis,
    settings: Settings,
    graph,
    agent: CreatureAgent,
) -> None:
    """
    Run one LangGraph tick and store the result via AgentService for Unity to poll.

    Job lifecycle (managed by AgentService):
      "pending"            — set by the router before this task starts
      {"status":"done",…}  — written here on success
      {"status":"error"}   — written here on failure; Unity aborts polling immediately
    """
    svc = AgentService(redis, settings)

    try:
        result = await graph.ainvoke({
            "raw_payload": payload,
            "messages": [],
            "tick": agent.memory.tick_count,
            "available_actions": agent.body.available_actions,
            "perception": None,
            "perception_error": None,
            "memory_context": None,
            "chosen_action": None,
            "reasoning": None,
            "action_result": None,
        })

        action_result = result.get("action_result") or {}
        kwargs = action_result.get("kwargs") or {}

        await svc.complete_job(job_id, {
            "action": action_result.get("action", "wait"),
            "x": float(kwargs.get("x", 0.0)),
            "y": float(kwargs.get("y", 0.0)),
            "z": float(kwargs.get("z", 0.0)),
            "target": str(kwargs.get("target", "")),
            "reasoning": result.get("reasoning", ""),
        })

    except Exception:
        logger.exception("Agent job %s failed", job_id)
        await svc.fail_job(job_id)
