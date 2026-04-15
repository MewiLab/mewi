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

logger = logging.getLogger(__name__)


async def agent_thinking_task(
    *,
    creature_id: str,
    snapshot: dict,
    supabase: Client,
    redis: aioredis.Redis,
    settings: Settings,
) -> None:
    """
    Agent thinking pipeline triggered by a Unity game-world snapshot.

    TODO: Replace the stub with a real LLM / LangGraph call using snapshot.
    """
    agent_svc = AgentService(redis, settings)

    try:
        await agent_svc.set_status(creature_id, "thinking")

        # ── Replace this block with LangGraph / LLM call ─────
        #TODO
        await asyncio.sleep(3)
        # ──────────────────────────────────────────────────────

    except Exception:
        logger.exception("Agent thinking failed for creature %s", creature_id)
    finally:
        # Always restore idle — prevents Unity cat from being stuck in "thinking"
        await agent_svc.set_status(creature_id, "idle")
