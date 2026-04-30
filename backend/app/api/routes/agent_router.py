from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import AgentDep, AgentServiceDep, RedisDep, SettingsDep
from app.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ── Unity payload sub-models ─────────────────────────────────────────────────

class Location(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class SelfState(BaseModel):
    location:       Location = Field(default_factory=Location)
    current_action: str      = "idle"


class MoodState(BaseModel):
    fear:      float = Field(0.0, ge=0.0, le=1.0)
    trust:     float = Field(0.0, ge=0.0, le=1.0)
    curiosity: float = Field(0.5, ge=0.0, le=1.0)
    social:    float = Field(0.0, ge=0.0, le=1.0)
    energy:    float = Field(1.0, ge=0.0, le=1.0)


class HealthState(BaseModel):
    hunger: float = Field(0.0, ge=0.0, le=1.0)


class EntitySnapshot(BaseModel):
    id:        str       = ""
    tags:      list[str] = Field(default_factory=list)
    distance:  float     = 0.0
    direction: str       = ""


class TickPayload(BaseModel):
    """
    One environment snapshot pushed from Unity each game tick.

    creature_id is a URL path parameter — not part of the sensor payload.
    The `self` field is aliased to `self_state` to avoid the Python keyword.
    Send JSON with key "self"; receive it as self_state in Python.
    """
    model_config = ConfigDict(populate_by_name=True)

    request_id: str                 = Field("",  alias="requestId")
    self_state: SelfState           = Field(default_factory=SelfState, alias="self")
    mood:       MoodState           = Field(default_factory=MoodState)
    health:     HealthState         = Field(default_factory=HealthState)
    entities:   list[EntitySnapshot] = Field(default_factory=list)


class TickResponse(BaseModel):
    tick:      int | None            = None
    action:    dict[str, Any] | None = None
    reasoning: str | None            = None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/tick/{creature_id}", response_model=TickResponse)
async def agent_tick(
    creature_id: str,
    payload: TickPayload,
    service: AgentServiceDep,
    background_tasks: BackgroundTasks,
):
    """
    Run one full agent tick.

    Unity calls this every frame with the current environment snapshot.
    `creature_id` is taken from the URL path so the sensor payload stays
    schema-clean.  The service buffers N snapshots then persists a single
    semantic summary row (X-to-1 compression).
    """
    try:
        result = await service.run_full_tick_flow(
            creature_id,
            payload.model_dump(by_alias=True),
            background_tasks,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except Exception as exc:
        logger.exception("Unhandled error in agent_tick")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error: {type(exc).__name__} - {exc}",
        )

    return TickResponse(
        tick=result.get("tick"),
        action=result.get("action_result"),
        reasoning=result.get("reasoning"),
    )


@router.get("/status/{creature_id}")
async def get_agent_status(creature_id: str, redis: RedisDep):
    """Query the creature's current real-time status (used by Unity to drive animations)."""
    raw = await redis.get(f"agent_status:{creature_id}")
    agent_status = (raw.decode() if isinstance(raw, bytes) else raw) or "idle"
    return {
        "creature_id": creature_id,
        "status":      agent_status,
        "is_thinking": agent_status == "thinking",
    }


# ── Debug / introspection ─────────────────────────────────────────────────────

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
