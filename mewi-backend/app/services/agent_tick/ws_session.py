import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.models import AgentWsRegisteredResponse, AgentWsRegisterMessage, AgentWsTickEnvelope, TickPayload
from app.services.agent_tick.tick_service import AgentTickInFlightError, AgentTickService

logger = logging.getLogger(__name__)


class AgentTickWebSocketSession:
    """One shared Unity websocket carrying ticks for many creatures."""

    def __init__(self, websocket: WebSocket, service: AgentTickService):
        self._websocket = websocket
        self._service = service
        self._send_lock = asyncio.Lock()
        self._registered: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        await self._websocket.accept()
        logger.info("Agent shared websocket connected")

        try:
            while True:
                await self._handle_next_message()
        except WebSocketDisconnect:
            logger.info(
                "Agent shared websocket disconnected registered=%s tasks=%s",
                sorted(self._registered),
                len(self._tasks),
            )
        except Exception:
            logger.exception(
                "Agent shared websocket crashed registered=%s tasks=%s",
                sorted(self._registered),
                len(self._tasks),
            )
            try:
                await self._websocket.close(code=1011)
            except RuntimeError:
                pass
        finally:
            await self._cancel_tasks()

    async def _handle_next_message(self) -> None:
        try:
            raw_payload = await self._websocket.receive_json()
        except ValueError as exc:
            await self._send(_error_response("", "", f"Invalid JSON payload: {exc}"))
            return

        if not isinstance(raw_payload, dict):
            await self._send(_error_response("", "", "Shared websocket message must be a JSON object"))
            return

        message_type = str(raw_payload.get("type") or "").strip().lower()
        if message_type == "register":
            await self._handle_register(raw_payload)
            return

        if message_type != "tick":
            await self._send(
                _error_response(
                    "",
                    _raw_request_id(raw_payload),
                    f"Unsupported websocket message type: {message_type or '(missing)'}",
                )
            )
            return

        await self._handle_tick(raw_payload)

    async def _handle_register(self, raw_payload: dict[str, Any]) -> None:
        try:
            message = AgentWsRegisterMessage.model_validate(raw_payload)
        except ValidationError as exc:
            await self._send(_error_response("", _raw_request_id(raw_payload), f"Invalid register message: {exc}"))
            return

        before = set(self._registered)
        self._registered.update(message.creature_ids)
        added = sorted(self._registered - before)
        logger.info(
            "Agent shared websocket registered creatures added=%s total=%s all=%s",
            added,
            len(self._registered),
            sorted(self._registered),
        )
        await self._send(AgentWsRegisteredResponse(creature_ids=sorted(self._registered)).model_dump())

    async def _handle_tick(self, raw_payload: dict[str, Any]) -> None:
        try:
            envelope = AgentWsTickEnvelope.model_validate(raw_payload)
        except ValidationError as exc:
            await self._send(_error_response("", _raw_request_id(raw_payload), f"Invalid tick envelope: {exc}"))
            return

        creature_id = envelope.creature_id
        request_id = envelope.request_id
        if not creature_id:
            await self._send(_error_response("", request_id, "tick envelope missing creature_id/agent_id"))
            return
        if not request_id:
            await self._send(_error_response(creature_id, "", "tick envelope missing requestId"))
            return

        if creature_id not in self._registered:
            self._registered.add(creature_id)
            logger.info(
                "Agent shared websocket implicitly registered creature_id=%s registered=%s",
                creature_id,
                sorted(self._registered),
            )

        tick_payload = _tick_payload_from_ws(raw_payload)
        _log_unity_snapshot(creature_id, raw_payload, tick_payload)

        try:
            payload = TickPayload.model_validate(tick_payload)
        except ValidationError as exc:
            await self._send(_error_response(creature_id, request_id, f"Invalid tick payload: {exc}"))
            return

        task = asyncio.create_task(self._process_tick(creature_id, request_id, payload))
        self._tasks.add(task)
        task.add_done_callback(
            lambda done, creature_id=creature_id, request_id=request_id: self._on_task_done(
                creature_id,
                request_id,
                done,
            )
        )

    async def _process_tick(self, creature_id: str, request_id: str, payload: TickPayload) -> None:
        try:
            accepted = await self._service.submit_tick(
                creature_id,
                payload.model_dump(by_alias=True),
            )
            logger.info(
                "Agent shared websocket accepted tick creature_id=%s request_id=%s job_id=%s queue_depth=%s",
                creature_id,
                request_id,
                accepted.get("job_id"),
                accepted.get("queue_depth"),
            )
        except AgentTickInFlightError as exc:
            logger.warning(
                "Agent shared websocket rejected in-flight duplicate creature_id=%s request_id=%s existing_request_id=%s",
                creature_id,
                request_id,
                exc.existing_request_id,
            )
            await self._send(_error_response(creature_id, request_id, str(exc)))
            return
        except RuntimeError as exc:
            await self._send(_error_response(creature_id, request_id, str(exc)))
            return
        except Exception as exc:
            logger.exception("Failed to submit shared websocket tick creature_id=%s request_id=%s", creature_id, request_id)
            await self._send(
                _error_response(
                    creature_id=creature_id,
                    request_id=request_id,
                    error=f"Error: {type(exc).__name__} - {exc}",
                )
            )
            return

        job_id = accepted["job_id"]
        job = await self._service.wait_for_final_job(job_id)
        if not job:
            await self._send(
                _error_response(
                    creature_id=creature_id,
                    request_id=request_id,
                    error=f"Timed out waiting for tick job {job_id}",
                    job_id=job_id,
                )
            )
            return

        response = _shared_websocket_plan_response(job, creature_id, request_id)
        await self._send(response)
        logger.info(
            "Agent shared websocket sent response creature_id=%s request_id=%s job_id=%s status=%s",
            creature_id,
            request_id,
            job_id,
            response.get("status"),
        )

    async def _send(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self._websocket.send_json(payload)

    def _on_task_done(self, creature_id: str, request_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return

        exc = task.exception()
        if exc:
            logger.error(
                "Agent shared websocket task failed creature_id=%s request_id=%s",
                creature_id,
                request_id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def _cancel_tasks(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            with contextlib.suppress(Exception):
                await asyncio.gather(*self._tasks, return_exceptions=True)


def _tick_payload_from_ws(raw_payload: Any) -> Any:
    if not isinstance(raw_payload, dict) or not isinstance(raw_payload.get("snapshot"), dict):
        return {}

    payload = dict(raw_payload["snapshot"])
    action_result = raw_payload.get("report")
    if isinstance(action_result, dict):
        payload["action_result"] = action_result

    request_id = raw_payload.get("requestId") or raw_payload.get("request_id")
    if request_id and not payload.get("requestId"):
        payload["requestId"] = request_id

    agent_id = raw_payload.get("agent_id")
    if agent_id and not payload.get("agent_id"):
        payload["agent_id"] = agent_id

    return payload


def _log_unity_snapshot(creature_id: str, raw_payload: Any, tick_payload: Any) -> None:
    request_id = _raw_request_id(tick_payload)
    snapshot_json = _to_log_json(tick_payload)
    logger.info(
        "[UnitySnapshot] creature_id=%s request_id=%s payload=%s",
        creature_id,
        request_id,
        snapshot_json,
    )

    if raw_payload is not tick_payload:
        logger.debug(
            "[UnitySnapshotEnvelope] creature_id=%s request_id=%s raw=%s",
            creature_id,
            request_id,
            _to_log_json(raw_payload),
        )


def _websocket_plan_response(job: dict[str, Any]) -> dict[str, Any]:
    plan_steps = job.get("plan_steps") or []
    dialogue = job.get("dialogue") or []

    return {
        "type": "plan",
        "job_id": job.get("job_id", ""),
        "creature_id": job.get("creature_id", ""),
        "request_id": job.get("request_id", ""),
        "status": job.get("status", "pending"),
        "tick": job.get("tick"),
        "intent": job.get("intent"),
        "intent_proposals": job.get("intent_proposals"),
        "intent_affordances": job.get("intent_affordances"),
        "memory_state": job.get("memory_state"),
        "place_memory": job.get("place_memory"),
        "social_context": job.get("social_context"),
        "actions": plan_steps,
        "dialogue": dialogue,
        "wake_targets": job.get("wake_targets", []),
        "social_effects": job.get("social_effects", []),
        "tool_results": job.get("tool_results", []),
        "reasoning": job.get("reasoning"),
        "error": job.get("error"),
    }


def _shared_websocket_plan_response(
    job: dict[str, Any],
    creature_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = _websocket_plan_response(job)

    job_creature_id = str(response.get("creature_id") or "")
    job_request_id = str(response.get("request_id") or "")
    if job_creature_id and job_creature_id != creature_id:
        logger.warning(
            "Agent shared websocket overriding mismatched job creature_id=%s with envelope creature_id=%s request_id=%s",
            job_creature_id,
            creature_id,
            request_id,
        )
    if job_request_id and job_request_id != request_id:
        logger.warning(
            "Agent shared websocket overriding mismatched job request_id=%s with envelope request_id=%s creature_id=%s",
            job_request_id,
            request_id,
            creature_id,
        )

    response["creature_id"] = creature_id
    response["request_id"] = request_id
    return response


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


def _to_log_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)
