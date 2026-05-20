import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import AgentTickServiceDep, verify_api_key
from app.models import TickPayload

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(verify_api_key)])
logger = logging.getLogger(__name__)

WS_JOB_POLL_INTERVAL_SECONDS = 0.25
WS_JOB_TIMEOUT_SECONDS = 0.0


@router.websocket("/ws/{creature_id}")
async def agent_tick_ws(
    websocket: WebSocket,
    creature_id: str,
    service: AgentTickServiceDep,
) -> None:
    """
    Unity websocket tick loop.

    Unity is the cadence authority: each message contains a full fresh
    snapshot plus the previous plan report, and each response contains the next
    ordered action list.
    """
    await websocket.accept()
    logger.info("Agent websocket connected creature_id=%s", creature_id)

    try:
        while True:
            try:
                raw_payload = await websocket.receive_json()
            except ValueError as exc:
                await websocket.send_json(
                    _error_response(
                        creature_id=creature_id,
                        request_id="",
                        error=f"Invalid JSON payload: {exc}",
                    )
                )
                continue

            tick_payload = _tick_payload_from_ws(raw_payload)

            try:
                payload = TickPayload.model_validate(tick_payload)
            except ValidationError as exc:
                await websocket.send_json(
                    _error_response(
                        creature_id=creature_id,
                        request_id=_raw_request_id(tick_payload),
                        error=f"Invalid tick payload: {exc}",
                    )
                )
                continue

            try:
                accepted = await service.submit_tick(
                    creature_id,
                    payload.model_dump(by_alias=True),
                )
            except RuntimeError as exc:
                await websocket.send_json(
                    _error_response(
                        creature_id=creature_id,
                        request_id=payload.request_id,
                        error=str(exc),
                    )
                )
                continue
            except Exception as exc:
                logger.exception("Failed to submit websocket tick creature_id=%s", creature_id)
                await websocket.send_json(
                    _error_response(
                        creature_id=creature_id,
                        request_id=payload.request_id,
                        error=f"Error: {type(exc).__name__} - {exc}",
                    )
                )
                continue

            job_id = accepted["job_id"]
            job = await _wait_for_final_job(service, job_id)
            if not job:
                await websocket.send_json(
                    _error_response(
                        creature_id=creature_id,
                        request_id=payload.request_id,
                        error=f"Timed out waiting for tick job {job_id}",
                        job_id=job_id,
                    )
                )
                continue

            await websocket.send_json(_websocket_plan_response(job))

    except WebSocketDisconnect:
        logger.info("Agent websocket disconnected creature_id=%s", creature_id)
    except Exception:
        logger.exception("Agent websocket crashed creature_id=%s", creature_id)
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass


async def _wait_for_final_job(
    service: AgentTickServiceDep,
    job_id: str,
    timeout_seconds: float = WS_JOB_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds if timeout_seconds > 0 else None

    while deadline is None or loop.time() < deadline:
        job = await service.get_job(job_id)
        if job and job.get("status") in {"done", "error"}:
            return job
        await asyncio.sleep(WS_JOB_POLL_INTERVAL_SECONDS)

    return None


def _tick_payload_from_ws(raw_payload: Any) -> Any:
    """
    Accept both legacy raw snapshots and the ADR-004 websocket envelope.

    Envelope shape:
      {type: "tick", report: <previous nested result>, snapshot: <TickPayload>}

    The graph receives the previous action result inside the same payload as
    the fresh snapshot, so prompt construction sees ordered cause and effect.
    """
    if not isinstance(raw_payload, dict):
        return raw_payload

    if raw_payload.get("type") != "tick" or not isinstance(raw_payload.get("snapshot"), dict):
        return raw_payload

    payload = dict(raw_payload["snapshot"])
    action_result = (
        raw_payload.get("report")
        or raw_payload.get("action")
        or raw_payload.get("action_result")
    )
    if isinstance(action_result, dict):
        payload["action_result"] = action_result

    request_id = raw_payload.get("requestId") or raw_payload.get("request_id")
    if request_id and not payload.get("requestId"):
        payload["requestId"] = request_id

    agent_id = raw_payload.get("agent_id")
    if agent_id and not payload.get("agent_id"):
        payload["agent_id"] = agent_id

    return payload


def _websocket_plan_response(job: dict[str, Any]) -> dict[str, Any]:
    plan_steps = job.get("plan_steps") or []

    return {
        "type": "plan",
        "job_id": job.get("job_id", ""),
        "creature_id": job.get("creature_id", ""),
        "request_id": job.get("request_id", ""),
        "status": job.get("status", "pending"),
        "tick": job.get("tick"),
        "actions": plan_steps,
        "reasoning": job.get("reasoning"),
        "error": job.get("error"),
    }


def _error_response(
    creature_id: str,
    request_id: str,
    error: str,
    job_id: str = "",
) -> dict[str, Any]:
    return {
        "type": "error",
        "job_id": job_id,
        "creature_id": creature_id,
        "request_id": request_id,
        "status": "error",
        "tick": None,
        "actions": [],
        "reasoning": error,
        "error": error,
    }


def _raw_request_id(raw_payload: Any) -> str:
    if isinstance(raw_payload, dict):
        value = raw_payload.get("requestId") or raw_payload.get("request_id")
        return str(value) if value is not None else ""
    return ""
