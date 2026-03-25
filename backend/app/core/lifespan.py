"""
App lifespan: create expensive resources once, share via app.state, tear down on exit.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.redis import create_redis, close_redis
from app.core.supabase import create_supabase

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Startup 
    logger.info("Connecting to Supabase…")
    app.state.supabase = create_supabase(settings)
    logger.info("Connecting to Redis…")
    app.state.redis = create_redis(settings)
    logger.info("All client ready")
    yield

    # Shutdown 
    logger.info("Closing Redis pool…")
    await close_redis(app.state.redis)
    logger.info("Shutdown complete.")
