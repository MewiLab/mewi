"""
AgentWorker: periodic autonomous agent tick loop.

Subclass of BaseWorker — runs _run_once() every interval_seconds.
Each tick: fetch body state → invoke LangGraph brain → persist result.
"""

import logging

import redis.asyncio as aioredis
from supabase import Client

from app.agent.creature_agent import CreatureAgent
from app.core.config import Settings
from app.services.memory_service import persist_tick
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class AgentWorker(BaseWorker):
    """Autonomous agent tick loop. One _run_once() = one LangGraph tick."""

    name = "agent_worker"

    def __init__(
        self,
        *,
        creature_id: str,
        agent: CreatureAgent,
        graph,
        redis: aioredis.Redis,
        supabase: Client,
        settings: Settings,
        interval_seconds: float,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds)
        self._creature_id = creature_id
        self._agent = agent
        self._graph = graph
        self._redis = redis
        self._supabase = supabase
        self._settings = settings

    async def _run_once(self) -> None:
        status_key = f"creature:{self._creature_id}:status"
        await self._redis.set(status_key, "thinking")
        try:
            body_state = await self._agent.body.get_state()
            await self._graph.ainvoke({
                "raw_payload": body_state,
                "messages": [],
                "tick": self._agent.memory.tick_count,
                "available_actions": self._agent.body.available_actions,
                "perception": None,
                "perception_error": None,
                "memory_context": None,
                "chosen_action": None,
                "reasoning": None,
                "action_result": None,
            })
            await persist_tick(self._agent, self._supabase, self._redis)
        finally:
            await self._redis.set(status_key, "idle")
