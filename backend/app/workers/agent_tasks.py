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
from app.services.agent import AgentService

logger = logging.getLogger(__name__)


async def agent_thinking_task(
    *,
    log_id: str,
    user_id: str,
    content: str,
    supabase: Client,
    redis: aioredis.Redis,
    settings: Settings,
) -> None:
    """
    Simulates the agent thinking about a new microlog entry.

    TODO: Replace the dummy reply with a real LLM call via LangGraph.
    """
    agent_svc = AgentService(redis, settings)
    repo = MicrologRepository(supabase)

    try:
        await agent_svc.set_status(user_id, "thinking")

        # ── Replace this block with LangGraph / LLM call ─────
        await asyncio.sleep(3)
        reply = f"喵～聽起來你今天過得不錯：{content[:20]}…"
        # ──────────────────────────────────────────────────────

        repo.update(log_id, MicrologUpdate(reply=reply))

    except Exception:
        logger.exception("Agent thinking failed for log %s", log_id)
    finally:
        # Always restore idle — prevents Unity cat from being stuck in "thinking"
        await agent_svc.set_status(user_id, "idle")
