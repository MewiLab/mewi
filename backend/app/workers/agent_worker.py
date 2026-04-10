import logging
from typing import Any

import redis.asyncio as aioredis
from supabase import Client

from app.core.config import Settings
from app.workers.base import BaseWorker
from app.agent.creature_agent import CreatureAgent
from app.services.agent_service import AgentService
from app.services.memory_service import persist_tick

logger = logging.getLogger(__name__)


class AgentWorker(BaseWorker):
    """
    Runs the full agent think loop every N seconds.
    Manages thinking/idle status around the graph call.
    """
    name = "agent_worker"

    def __init__(
        self,
        *,
        creature_id: str,
        agent: CreatureAgent,
        graph: Any,
        redis: aioredis.Redis,
        supabase: Client,
        settings: Settings,
        interval_seconds: float = 10.0,
    ):
        super().__init__(interval_seconds)
        self._creature_id = creature_id
        self._agent       = agent
        self._graph       = graph
        self._redis       = redis
        self._supabase    = supabase
        self._agent_svc   = AgentService(redis=redis, settings=settings)

    async def _run_once(self) -> None:
        await self._agent_svc._set_status(self._creature_id, "thinking")
        try:
            raw_payload = await self._agent.body.get_state()
            result = await self._graph.ainvoke({
                "creature_id":       self._creature_id,
                "raw_payload":       raw_payload,
                "messages":          [],
                "tick":              self._agent.memory.tick_count,
                "available_actions": self._agent.body.available_actions,
                "perception":        None,
                "perception_error":  None,
                "memory_context":    None,
                "chosen_action":     None,
                "reasoning":         None,
                "action_result":     None,
            })
            logger.info(
                "Tick %s — action: %s",
                result.get("tick"),
                result.get("action_result", {}).get("action"),
            )
            await persist_tick(self._agent, self._supabase, self._redis)
        finally:
            await self._agent_svc._set_status(self._creature_id, "idle")