from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import AgentDep, AgentServiceDep, verify_api_key
from app.core.logger import get_logger
from app.schemas import (
    ActionReportPayload,
    ActionReportResponse,
    ActionReportsResponse,
    AgentResultResponse,
    AgentStatusResponse,
    RuntimeClearResponse,
    TickPayload,
    TickResponse,
)

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
    request_id = payload.request_id
    logger.info(
        "[AGENT TICK IN] creature=%s request_id=%s entities=%d",
        creature_id,
        request_id or "(none)",
        len(payload.entities),
    )
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

    logger.info(
        "[AGENT TICK OUT] creature=%s request_id=%s status=%s buffered=%s latency_ms=%.1f",
        creature_id,
        request_id or "(none)",
        tick_response.status or "(none)",
        tick_response.buffered_count,
        latency_ms,
    )

    if result.get("status") == "processing":
        return JSONResponse(
            content=tick_response.model_dump(),
            status_code=status.HTTP_202_ACCEPTED,
        )
    return tick_response


@router.get("/status/{creature_id}", response_model=AgentStatusResponse)
async def get_agent_status(creature_id: str, service: AgentServiceDep):
    """Query the creature's current real-time status (used by Unity to drive animations)."""
    _t0 = time.perf_counter()
    payload = await service.get_status_payload(creature_id)
    _ms = (time.perf_counter() - _t0) * 1000
    logger.info("[DB READ] Redis GET agent_status %.1f ms — creature=%s  status=%s",
                _ms, creature_id, payload["status"])
    return payload


@router.get("/result/{creature_id}", response_model=AgentResultResponse)
async def get_agent_result(
    creature_id: str,
    service: AgentServiceDep,
    consume: bool = Query(False, description="Delete the stored result after reading it."),
):
    """Fetch the latest completed brain decision for Unity."""
    return await service.get_latest_result(creature_id, consume=consume)


@router.get("/tick/result/{creature_id}", response_model=AgentResultResponse)
async def get_agent_tick_result_compat(
    creature_id: str,
    service: AgentServiceDep,
    consume: bool = Query(False, description="Delete the stored result after reading it."),
):
    """Compatibility alias for older Unity bridges that poll a tick-result path."""
    return await service.get_latest_result(creature_id, consume=consume)


@router.post("/report", response_model=ActionReportResponse)
async def report_agent_action(report: ActionReportPayload, service: AgentServiceDep):
    """Receive Unity-side execution status for an LLM command."""
    return await service.record_action_report(report.model_dump(by_alias=True))


@router.get("/reports/{creature_id}", response_model=ActionReportsResponse)
async def get_agent_reports(
    creature_id: str,
    service: AgentServiceDep,
    limit: int = Query(20, ge=1, le=50),
):
    """Recent Unity action callbacks for debugging local integration."""
    return await service.get_action_reports(creature_id, limit=limit)


@router.delete("/runtime/{creature_id}", response_model=RuntimeClearResponse)
async def clear_agent_runtime(creature_id: str, service: AgentServiceDep):
    """Clear runtime Redis keys for a creature during local development."""
    return await service.clear_runtime_state(creature_id)


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
