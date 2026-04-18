import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logger import setup_logging
from app.core.redis import create_redis, close_redis
from app.core.supabase import create_supabase
from app.agent.creature_agent import create_creature_agent
from app.agent.llm_provider import create_llm_provider
from app.agent.graph import build_creature_graph
from app.services.memory_service import hydrate_agent

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings=settings)
    logger.info("Starting up...")
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
    
    llm = create_llm_provider(settings.llm)
    app.state.graph = build_creature_graph(app.state.agent, llm).compile()

    logger.info("Hydrating agent memory from last session…")
    await hydrate_agent(
        agent=app.state.agent,
        supabase=app.state.supabase,
        redis=app.state.redis,
    )
    yield

    # Shutdown
    logger.info("Shutting down agent…")
    await app.state.agent.disconnect()
    logger.info("Closing Redis pool…")
    await close_redis(app.state.redis)
    logger.info("Shutdown complete.")