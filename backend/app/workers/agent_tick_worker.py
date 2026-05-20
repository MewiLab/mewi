import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.agent.creature_runtime import CreatureRuntime
from app.agent.prompt_loader import DEFAULT_PERSONA_KEY, normalize_creature_id
from app.services.agent_tick_service import AgentTickService

logger = logging.getLogger(__name__)


class AgentTickWorker:
    """Consumes queued tick jobs and runs them through the shared behavior graph."""

    def __init__(
        self,
        service: AgentTickService,
        graph: Any,
        personas: dict[str, str] | None = None,
    ):
        self._service = service
        self._graph = graph
        self._personas = personas or {}
        self._default_persona = self._personas.get(DEFAULT_PERSONA_KEY, "")
        self._runtimes: dict[str, CreatureRuntime] = {}
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Agent tick worker started")
        while self._running:
            try:
                await self.process_one(timeout=5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Agent tick worker failed; continuing")
                await asyncio.sleep(1)
        logger.info("Agent tick worker stopped")

    def stop(self) -> None:
        self._running = False

    async def process_one(self, timeout: int = 5) -> bool:
        job = await self._service.get_next_job(timeout=timeout)
        if not job:
            return False

        creature_id = job["creature_id"]
        job_id = job["job_id"]
        payload = job["payload"]
        await self._service.mark_processing(creature_id, job_id)

        try:
            runtime = self._runtimes.get(creature_id)
            if runtime is None:
                runtime = CreatureRuntime(persona=self._persona_for(creature_id))
                self._runtimes[creature_id] = runtime
                logger.info(
                    "Created CreatureRuntime for creature_id=%s persona=%s",
                    creature_id,
                    self._persona_key_for(creature_id),
                )
            result = await self._graph.ainvoke(runtime.state_for_tick(creature_id, payload))
            await self._service.publish_result(creature_id, job_id, {
                "request_id": job.get("request_id", ""),
                "tick": result.get("tick"),
                "action_result": result.get("action_result"),
                "plan_steps": result.get("plan_steps", []),
                "reasoning": result.get("reasoning", ""),
            })
            return True
        except Exception as exc:
            logger.exception("Tick job failed for creature=%s", creature_id)
            await self._service.publish_error(creature_id, job_id, str(exc))
            return False

    async def close(self, task: asyncio.Task | None = None) -> None:
        self.stop()
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def _persona_for(self, creature_id: str) -> str:
        return self._personas.get(self._persona_key_for(creature_id), self._default_persona)

    @staticmethod
    def _persona_key_for(creature_id: str) -> str:
        return normalize_creature_id(creature_id)
