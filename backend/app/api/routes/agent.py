"""
/agent routes — real-time status and background thinking trigger.
"""

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import RedisDep, SettingsDep, SupabaseDep
from app.services.agent import AgentService
from app.workers.agent_tasks import agent_thinking_task
from app.models.creature  import CreatureThinkRequest
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


@router.post("/think", status_code=202)
async def trigger_agent_think(
    body: CreatureThinkRequest,
    background_tasks: BackgroundTasks,
    db: SupabaseDep,
    redis: RedisDep,
    settings: SettingsDep,
):
    """Enqueue the agent thinking pipeline for a microlog entry."""
    background_tasks.add_task(
        agent_thinking_task,
        creature_id=body.creature_id,
        snapshot=body.snapshot,
        supabase=db,
        redis=redis,
        settings=settings,
    )
    return {"queued": True}
    
    
