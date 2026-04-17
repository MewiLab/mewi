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
    settings: SettingsDep,
    background_tasks: BackgroundTasks,
):
    """Run one full agent tick."""
    # Assuming the client passes the ID in the payload. Adjust this if it 
    # lives on the agent object itself (e.g., agent.id)
    creature_id = payload.get("user_id") or payload.get("creature_id")
    
    if not creature_id:
        # Fallback or raise an HTTPException depending on your requirements
        creature_id = "default_creature"

    svc = AgentService(
        redis=redis,
        settings=settings,
        agent=agent,
        graph=graph,
        supabase=supabase
    )
    
    result = await svc.run_tick(
        creature_id=creature_id,
        payload=payload,
        background_tasks=background_tasks
    )

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