"""
Background worker: agent "thinking" pipeline.

Runs as a FastAPI BackgroundTask. All dependencies are passed explicitly
so the worker is testable in isolation.
"""

import asyncio
import logging

import redis.asyncio as aioredis
from supabase import Client

from app.core.config import Settings
from app.models.microlog import MicrologUpdate
from app.repositories.microlog_repo import MicrologRepository
from app.services.agent_service import AgentService
from app.agent.creature_agent import create_creature_agent
from app.agent.graph import build_creature_graph

logger = logging.getLogger(__name__)


async def agent_thinking_task(
    *,
    creature_id: str,
    snapshot: dict,
    supabase: Client,
    redis: aioredis.Redis,
    settings: Settings,
) -> None:
    agent_svc = AgentService(redis, settings)

    try:
        print(f"\n🚀 [Agent Task] Start: {creature_id}")
        await agent_svc.set_status(creature_id, "thinking")
        
        agent = create_creature_agent(unity_url=settings.unity_bridge_url)
        graph = build_creature_graph(agent).compile() 

        print("🧠 [Agent Task] Invoking LLM (Gemma 3)...")
        
        result = await graph.ainvoke({
            "raw_payload": snapshot,
            "tick": agent.memory.tick_count,
            "available_actions": agent.body.available_actions,
            "messages": [],
            "perception": None,
            "perception_error": None,
            "memory_context": None,
            "chosen_action": None,
            "reasoning": None,
            "action_result": None,
        })

        print("-" * 30)
        print(f"✨ [Agent Task] Success!")
        print(f"🤔 Thought: {result.get('reasoning')}")
        print(f"🎯 Action: {result.get('chosen_action')}")
        print("-" * 30)

    except Exception as e:
        print(f"💥 [Agent Task] Failed: {e}")
        logger.exception("Agent thinking failed for creature %s", creature_id)
    finally:
        print(f"💤 [Agent Task] Back to Idle\n")
        await agent_svc.set_status(creature_id, "idle")