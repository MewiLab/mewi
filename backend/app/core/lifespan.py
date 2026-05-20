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
from app.agent.prompt_loader import DEFAULT_PERSONA_KEY, load_persona_map
from app.services.agent_tick_service import AgentTickService
from app.workers.agent_tick_worker import AgentTickWorker

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
    app.state.behavior_graph = build_behavior_graph(llm).compile()
    app.state.creature_personas = load_persona_map(
        settings.agent_personas,
        default_persona=settings.agent_persona,
    )
    logger.info(
        "Loaded %d creature persona mapping(s): %s",
        len(app.state.creature_personas),
        ", ".join(sorted(app.state.creature_personas.keys())),
    )
    if DEFAULT_PERSONA_KEY not in app.state.creature_personas:
        logger.warning("Creature persona mapping has no default entry")

    logger.info("Creating agent tick service…")
    app.state.agent_tick_service = AgentTickService(
        redis=app.state.redis,
        settings=settings,
    )

    app.state.agent_tick_worker = AgentTickWorker(
        service=app.state.agent_tick_service,
        graph=app.state.behavior_graph,
        personas=app.state.creature_personas,
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
