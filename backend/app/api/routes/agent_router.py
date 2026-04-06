from typing import Any

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import RedisDep, SettingsDep, AgentDep, GraphDep, SupabaseDep
from app.services.agent_service import AgentService
from app.services.memory_service import persist_tick

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/status/{user_id}")
async def get_agent_status(
    user_id: str,
    redis: RedisDep,
    settings: SettingsDep,
):
    """Query the agent's current real-time status (used by Unity to drive animations)."""
    svc = AgentService(redis, settings)
    status = await svc.get_status(user_id)
    return {
        "user_id": user_id,
        "status": status,
        "is_thinking": status == "thinking",
    }


@router.post("/tick")
async def agent_tick(
    payload: dict[str, Any],
    agent: AgentDep,
    graph: GraphDep,
    supabase: SupabaseDep,
    redis: RedisDep,
    background_tasks: BackgroundTasks,
):
    """
    One tick of the agent's brain.

    Unity POSTs the environment + creature snapshot.
    The pre-compiled graph runs: perceive → remember → reason → act → reflect.
    Returns the chosen action and reasoning.

    This is the hot path — called every N seconds by Unity during gameplay.
    The graph was compiled once at startup (in lifespan.py), not per request.
    Persistence is non-blocking: written after the response via BackgroundTasks.
    """
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

    # Non-blocking write — doesn't slow down the Unity response
    background_tasks.add_task(persist_tick, agent, supabase, redis)

    return {
        "tick": result.get("tick"),
        "action": result.get("action_result"),
        "reasoning": result.get("reasoning"),
    }


# ─── Debug / introspection endpoints ────────────────────────────────────────
# These access the agent directly, no graph needed.


@router.get("/context")
async def get_agent_context(agent: AgentDep):
    """Full agent context — perception + memory + available actions."""
    return agent.get_context().to_prompt_context()


@router.get("/actions")
async def get_available_actions(agent: AgentDep):
    """List all actions the agent can currently perform."""
    return {
        "actions": agent.body.available_actions,
        "connected": agent.body.is_connected,
    }


@router.get("/memory")
async def get_agent_memory(agent: AgentDep, last_n: int = 5):
    """Recent memory — perception history + visited locations."""
    return agent.remember(last_n=last_n).to_prompt_context()