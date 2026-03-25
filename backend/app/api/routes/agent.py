"""
/agent routes — real-time status for Unity client polling.
"""

from fastapi import APIRouter

from app.api.deps import RedisDep, SettingsDep
from app.services.agent import AgentService

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