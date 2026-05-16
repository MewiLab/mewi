from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.deps import AgentDep, AgentServiceDep, RedisDep, SettingsDep, verify_api_key
from app.core.logger import get_logger
from app.schemas import TickPayload, TickResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(verify_api_key)])


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/tick/{creature_id}", responses={200: {"model": TickResponse}, 202: {"model": TickResponse}})
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

    Buffer ticks (1–9, 11–19): HTTP 200  {"status": "buffering", ...}
    Flush ticks  (10, 20):     HTTP 202  {"status": "processing", ...}
      — flush pipeline (LLM + DB writes) runs in the background;
        Unity polls GET /status/{creature_id} for is_thinking → idle.
    """
    _t0 = time.perf_counter()
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
    finally:
        latency_ms = round((time.perf_counter() - _t0) * 1000, 1)

    tick_response = TickResponse(
        tick           = result.get("tick"),
        action         = result.get("action_result"),
        reasoning      = result.get("reasoning"),
        status         = result.get("status"),
        buffered_count = result.get("count"),
        latency_ms     = latency_ms,
    )

    if result.get("status") == "processing":
        return JSONResponse(
            content=tick_response.model_dump(),
            status_code=status.HTTP_202_ACCEPTED,
        )
    return tick_response


@router.get("/status/{creature_id}")
async def get_agent_status(creature_id: str, redis: RedisDep):
    """Query the creature's current real-time status (used by Unity to drive animations)."""
    _t0 = time.perf_counter()
    raw = await redis.get(f"agent_status:{creature_id}")
    _ms = (time.perf_counter() - _t0) * 1000
    agent_status = (raw.decode() if isinstance(raw, bytes) else raw) or "idle"
    logger.info("[DB READ] Redis GET agent_status %.1f ms — creature=%s  status=%s",
                _ms, creature_id, agent_status)
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
