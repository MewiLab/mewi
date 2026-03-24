"""
App lifespan: create expensive resources once, share via app.state, tear down on exit.
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from supabase import create_client, Client
from fastapi import FastAPI

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # ── Startup ───────────────────────────────────────────────
    logger.info("Connecting to Supabase…")
    supabase: Client = create_client(settings.supabase_url, settings.supabase_key)
    app.state.supabase = supabase

    logger.info("Connecting to Redis…")
    redis_pool = aioredis.ConnectionPool.from_url(
        f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
        decode_responses=True,
    )
    app.state.redis = aioredis.Redis(connection_pool=redis_pool)

    logger.info("cat-brain is ready 🐱")
    yield

    # ── Shutdown ──────────────────────────────────────────────
    logger.info("Closing Redis pool…")
    await app.state.redis.aclose()
    await redis_pool.disconnect()
    logger.info("Shutdown complete.")
