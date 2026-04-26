from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AgentDep, AgentServiceDep, RedisDep, SettingsDep
from app.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ── Request / Response models (drives Swagger /docs visibility) ──────────────

class TickPayload(BaseModel):
    """
    One environment snapshot pushed from Unity each game tick.
    All fields map 1-to-1 to the perception_snapshots and creature_states
    SQL columns — no aliasing, no renaming.
    """
    creature_id:   str   = Field(...,   description="UUID of the creature (auto-created if new)")
    # Position
    pos_x:         float = Field(0.0,   description="World-space X")
    pos_y:         float = Field(0.0,   description="World-space Y")
    pos_z:         float = Field(0.0,   description="World-space Z")
    # Perception
    user_distance: float = Field(0.0,   ge=0.0, description="Distance to nearest user")
    user_velocity: float = Field(0.0,           description="User movement speed")
    time_of_day:   int   = Field(12,    ge=0, le=23, description="Hour (0–23)")
    # Internal creature states pushed from Unity → persisted to creature_states
    hunger:        float = Field(0.0,   ge=0.0, le=1.0)
    energy:        float = Field(1.0,   ge=0.0, le=1.0)
    mood:          float = Field(0.0,   ge=-1.0, le=1.0)
    curiosity:     float = Field(0.5,   ge=0.0, le=1.0)
    fear:          float = Field(0.0,   ge=0.0, le=1.0)


class TickResponse(BaseModel):
    tick:      int | None            = None
    action:    dict[str, Any] | None = None
    reasoning: str | None            = None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/tick", response_model=TickResponse)
async def agent_tick(
    payload: TickPayload,
    service: AgentServiceDep,
    background_tasks: BackgroundTasks,
):
    """
    Run one full agent tick.

    Unity calls this every frame with the current environment snapshot.
    The service handles: auto-registration, DB persistence, AI reasoning,
    and background memory writes.  This handler only validates + delegates.
    """
    try:
        result = await service.run_full_tick_flow(
            payload.model_dump(), background_tasks
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except Exception:
        logger.exception("Unhandled error in agent_tick")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error: {type(e).__name__} - {str(e)}",
        )

    return TickResponse(
        tick=result.get("tick"),
        action=result.get("action_result"),
        reasoning=result.get("reasoning"),
    )


@router.get("/status/{user_id}")
async def get_agent_status(
    user_id: str,
    redis: RedisDep,
    settings: SettingsDep,
):
    """Query the creature's current real-time status (used by Unity to drive animations)."""
    from app.services.agent_service import AgentService
    svc = AgentService(redis=redis, settings=settings)
    agent_status = await svc.get_status(user_id)
    return {
        "user_id":     user_id,
        "status":      agent_status,
        "is_thinking": agent_status == "thinking",
    }


# ── Debug / introspection (agent direct-access, no graph needed) ─────────────

@router.get("/context")
async def get_agent_context(agent: AgentDep):
    """Full agent context — perception + memory + available actions."""
    return agent.get_context().to_prompt_context()


@router.get("/actions")
async def get_available_actions(agent: AgentDep):
    """List all actions the agent can currently perform."""
    return {
        "actions":   agent.body.available_actions,
        "connected": agent.body.is_connected,
    }


@router.get("/memory")
async def get_agent_memory(agent: AgentDep, last_n: int = 5):
    """Recent memory — perception history + visited locations."""
    return agent.remember(last_n=last_n).to_prompt_context()
