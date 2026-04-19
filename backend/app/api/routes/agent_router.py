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
    graph: GraphDep,
    agent: AgentDep,
    supabase: SupabaseDep,
):
    """
    Enqueue one tick of the agent's brain and return immediately.

    Unity POSTs the environment + creature snapshot and receives a job_id.
    The LangGraph pipeline (perceive → remember → reason → act → reflect)
    runs in the background via AgentService.

    After the graph finishes, the worker asynchronously logs the decision
    to the micrologs table (Contextual Retrieval format) without blocking
    this response.

    Unity polls GET /agent/tick/result/{job_id} until status is "done" or "error".
    """
    job_id = uuid.uuid4().hex[:8]
    svc = AgentService(redis, settings)
    await svc.enqueue_job(job_id)
    background_tasks.add_task(
        run_agent_job,
        job_id=job_id,
        payload=payload,
        redis=redis,
        settings=settings,
        agent=agent,
        supabase=supabase,
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