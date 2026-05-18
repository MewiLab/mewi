import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logger import get_logger, setup_logging, shutdown_logging
from app.core.redis import create_redis, close_redis
from app.core.supabase import create_supabase
from app.agent.creature_agent import create_creature_agent
from app.agent.llm_provider import create_llm_provider
from app.agent.graph import build_creature_graph
from app.services.agent_service import AgentServiceState
from app.services.embedding_service import EmbeddingService
from app.services.semantic_service import SemanticService
from app.workers.microlog_worker import MicrologWorker

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings=settings)
    logger.info("Starting up...")

    # ── External connections ─────────────────────────────────────────────────
    logger.info("Connecting to Supabase…")
    app.state.supabase = create_supabase(settings)

    logger.info("Connecting to Redis…")
    app.state.redis = create_redis(settings)
    try:
        await app.state.redis.ping()
        logger.info("Redis ping OK")
    except Exception as exc:
        logger.error("Redis ping FAILED — service will be degraded: %s", exc)

    # ── Agent + graph (shared, process-scoped) ───────────────────────────────
    logger.info("Creating creature agent…")
    app.state.agent = create_creature_agent(unity_url=settings.unity_bridge_url)
    await app.state.agent.connect()

    logger.info("Compiling agent graph…")
    llm = create_llm_provider(settings.llm)
    app.state.graph = build_creature_graph(app.state.agent, llm).compile()

    # ── Process-scoped service singletons ────────────────────────────────────
    # AgentServiceState carries per-creature locks and last-snapshot IDs across
    # requests.  SemanticService is stateless but holds an EmbeddingService
    # client, so we build it once here and share it via app.state.
    app.state.agent_state = AgentServiceState()
    app.state.semantic_service = SemanticService(
        embedding_service=EmbeddingService(settings)
    )
    logger.info("AgentServiceState and SemanticService initialized")

    # ── Background workers ───────────────────────────────────────────────────
    # AgentWorker is removed: ticks are now driven by API requests per-creature.
    # Hydration is handled dynamically inside AgentService._hydrate_if_empty.
    microlog_worker = MicrologWorker(
        supabase=app.state.supabase,
        settings=settings,
    )
    worker_tasks = [
        asyncio.create_task(microlog_worker.start()),
    ]
    logger.info("MicrologWorker started")

    logger.info("All clients ready — serving requests")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Stopping workers…")
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)

    logger.info("Shutting down agent…")
    await app.state.agent.disconnect()

    logger.info("Closing Redis pool…")
    await close_redis(app.state.redis)

    logger.info("Shutdown complete.")
    shutdown_logging()
