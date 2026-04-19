"""
App lifespan: create expensive resources once, share via app.state, tear down on exit.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.redis import create_redis, close_redis
from app.core.supabase import create_supabase
from app.agent.creature_agent import create_creature_agent
from app.agent.graph import build_creature_graph

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Startup
    logger.info("Connecting to Supabase…")
    app.state.supabase = create_supabase(settings)
    logger.info("Connecting to Redis…")
    app.state.redis = create_redis(settings)
    
    logger.info("Creating creature agent…")
    app.state.agent = create_creature_agent(
        unity_url=settings.unity_bridge_url,
    )
    await app.state.agent.connect()
    logger.info("Compiling agent graph…")
    app.state.graph = build_creature_graph(app.state.agent).compile()
 
    logger.info("All clients ready")

    yield

    # Shutdown
    logger.info("Shutting down agent…")
    await app.state.agent.disconnect()
    logger.info("Closing Redis pool…")
    await close_redis(app.state.redis)
    logger.info("Shutdown complete.")