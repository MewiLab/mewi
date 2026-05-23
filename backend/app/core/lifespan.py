import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logger import get_logger, setup_logging, shutdown_logging
from app.core.redis import create_redis, close_redis
from app.core.supabase import create_supabase
from app.agent.llm_provider import create_llm_provider, log_llm_provider_selection
from app.agent.behavior_graph import build_behavior_graph
from app.agent.prompt_loader import PersonaManager
from app.repositories.memory_repo import MemoryRepository
from app.repositories.place_memory_cache import PlaceMemoryCache
from app.repositories.place_memory_repo import PlaceMemoryRepository
from app.services.agent_tick_service import AgentTickService
from app.services.memory_service import MemoryService
from app.services.place_memory_store import PlaceMemoryStoreChain
from app.services.place_memory_service import PlaceMemoryService
from app.social.service import SocialService
from app.workers.agent_tick_worker import AgentTickWorker
from app.world.state import WorldState

logger = get_logger(__name__)


def _configure_langsmith(settings) -> None:
    """Export LANGSMITH_* env vars so LangChain auto-tracing picks them up."""
    ls = settings.langsmith
    if not ls.tracing:
        return
    if not ls.api_key:
        logger.warning("LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty — tracing disabled")
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = ls.api_key
    os.environ["LANGSMITH_PROJECT"] = ls.project
    os.environ["LANGSMITH_ENDPOINT"] = ls.endpoint
    logger.info("LangSmith tracing enabled (project=%s)", ls.project)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings=settings)
    _configure_langsmith(settings)
    logger.info("Starting up...")

    # External connections 
    logger.info("Connecting to Supabase…")
    app.state.supabase = create_supabase(settings)

    logger.info("Connecting to Redis…")
    app.state.redis = create_redis(settings)
    redis_ok = True
    try:
        await app.state.redis.ping()
        logger.info("Redis ping OK")
    except Exception as exc:
        redis_ok = False
        logger.error("Redis ping FAILED — service will be degraded: %s", exc)

    # Behavior graph runtime 
    logger.info("Compiling behavior graph…")
    app.state.llm_provider_info = log_llm_provider_selection(settings.llm, logger)
    llm = create_llm_provider(settings.llm)
    app.state.place_memory_cache = PlaceMemoryCache(
        app.state.redis,
        ttl_seconds=settings.place_memory_ttl_seconds,
        refresh_seconds=settings.place_memory_refresh_seconds,
    )
    app.state.place_memory_repository = PlaceMemoryRepository(app.state.supabase)
    app.state.place_memory_store = PlaceMemoryStoreChain(
        app.state.place_memory_cache,
        app.state.place_memory_repository,
    )
    app.state.place_memory_service = PlaceMemoryService(app.state.place_memory_store)
    app.state.memory_repository = MemoryRepository(app.state.supabase)
    app.state.memory_service = MemoryService(app.state.memory_repository)
    app.state.world_state = WorldState()
    app.state.social_service = SocialService(world=app.state.world_state)
    app.state.behavior_graph = build_behavior_graph(
        llm,
        place_memory=app.state.place_memory_service,
        memory_service=app.state.memory_service,
        world=app.state.world_state,
        social=app.state.social_service,
    ).compile()
    app.state.persona_manager = PersonaManager.from_spec(
        settings.agent_personas,
        default_persona=settings.agent_persona,
    )
    logger.info(
        "Loaded %d creature persona mapping(s): %s",
        len(app.state.persona_manager.keys()),
        ", ".join(app.state.persona_manager.keys()),
    )
    if not app.state.persona_manager.has_default():
        logger.warning("Creature persona mapping has no default entry")

    logger.info("Creating agent tick service…")
    app.state.agent_tick_service = AgentTickService(
        redis=app.state.redis,
        settings=settings,
    )

    app.state.agent_tick_worker = AgentTickWorker(
        service=app.state.agent_tick_service,
        graph=app.state.behavior_graph,
        persona_manager=app.state.persona_manager,
    )
    app.state.agent_tick_worker_task = (
        asyncio.create_task(app.state.agent_tick_worker.start())
        if redis_ok else None
    )

    logger.info("All clients ready — serving requests")

    yield
    # Shutdown 
    logger.info("Stopping agent tick worker…")
    app.state.agent_tick_worker.stop()
    if app.state.agent_tick_worker_task:
        app.state.agent_tick_worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.agent_tick_worker_task

    logger.info("Closing Redis pool…")
    await close_redis(app.state.redis)

    logger.info("Shutdown complete.")
    shutdown_logging()
