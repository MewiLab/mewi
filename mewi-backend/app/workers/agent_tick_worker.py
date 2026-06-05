import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from app.agent.creature_runtime import CreatureRuntime
from app.agent.prompt_loader import PersonaManager
from app.cat_journal.raw_agent_graph import RawCatJournal
from app.services.agent_tick.tick_service import AgentTickService

if TYPE_CHECKING:
    from app.agent.memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)


class AgentTickWorker:
    """Consumes queued tick jobs and runs them through the shared behavior graph."""

    def __init__(
        self,
        service: AgentTickService,
        graph: Any,
        persona_manager: PersonaManager | None = None,
        raw_journal: RawCatJournal | None = None,
        memory_store: "MemoryStore | None" = None,
    ):
        self._service = service
        self._graph = graph
        self._persona_manager = persona_manager or PersonaManager()
        self._raw_journal = raw_journal
        self._memory_store = memory_store
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
                runtime = CreatureRuntime(
                    persona_manager=self._persona_manager,
                    creature_id=creature_id,
                    store=self._memory_store,
                )
                self._runtimes[creature_id] = runtime
                logger.info(
                    "Created CreatureRuntime for creature_id=%s persona=%s",
                    creature_id,
                    self._persona_manager.key_for(creature_id),
                )
            result = await self._graph.ainvoke(runtime.state_for_tick(creature_id, payload))
            unity_result = {
                "request_id": job.get("request_id", ""),
                "tick": result.get("tick"),
                "intent": result.get("intent_decision"),
                "intent_proposals": result.get("intent_proposals", []),
                "intent_affordances": result.get("intent_affordances"),
                "memory_state": result.get("memory_state"),
                "place_memory": result.get("place_memory_context"),
                "social_context": result.get("social_context"),
                "dialogue": result.get("dialogue", []),
                "wake_targets": result.get("wake_targets", []),
                "social_effects": result.get("social_effects", []),
                "tool_results": result.get("tool_results", []),
                "action_result": result.get("action_result"),
                "plan_steps": result.get("plan_steps", []),
                "reasoning": result.get("reasoning", ""),
            }
            await self._record_raw_graph_turn(
                creature_id=creature_id,
                job=job,
                payload=payload,
                result=result,
                unity_result=unity_result,
            )
            await self._service.publish_result(creature_id, job_id, unity_result)
            return True
        except Exception as exc:
            logger.exception("Tick job failed for creature=%s", creature_id)
            await self._service.publish_error(creature_id, job_id, str(exc))
            return False

    async def _record_raw_graph_turn(
        self,
        *,
        creature_id: str,
        job: dict[str, Any],
        payload: dict[str, Any],
        result: dict[str, Any],
        unity_result: dict[str, Any],
    ) -> None:
        if self._raw_journal is None:
            return
        try:
            path = await self._raw_journal.append_graph_turn(
                creature_id=creature_id,
                job=job,
                unity_payload=payload,
                graph_state=result,
                unity_result=unity_result,
            )
            logger.debug("Recorded raw graph turn creature=%s path=%s", creature_id, path)
        except Exception:
            logger.warning(
                "Failed to write raw graph turn creature=%s job_id=%s",
                creature_id,
                job.get("job_id", ""),
                exc_info=True,
            )

    async def close(self, task: asyncio.Task | None = None) -> None:
        self.stop()
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
