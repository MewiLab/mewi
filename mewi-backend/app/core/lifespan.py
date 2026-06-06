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
from app.cat_journal.raw_agent_graph import RawCatJournal
from app.repositories.composite_memory_store import CompositeMemoryStore
from app.repositories.micro_action_journal_store import MicroActionJournalStore
from app.repositories.place_memory_cache import PlaceMemoryCache
from app.repositories.place_memory_repo import PlaceMemoryRepository
from app.repositories.supabase_memory_store import SupabaseMemoryStore
from app.services.agent_tick.tick_service import AgentTickService
from app.repositories.place_memory_store import PlaceMemoryStoreChain
from app.agent.memory.place_memory_service import PlaceMemoryService
from app.services.perception.embedding_service import EmbeddingService
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


def _build_memory_store(settings, supabase, journal: RawCatJournal) -> CompositeMemoryStore:
    """Assemble the durable memory store.

    Supabase semantic summaries and the structural micro-action journal are
    always present. Optional mem0 vector memory is added only when
    MEMORY_GRAPH_ENABLED=true and the required endpoints are set. A failure
    there degrades to Phase 1 stores rather than blocking startup.
    """
    embedding = EmbeddingService(settings)
    stores: list = [
        SupabaseMemoryStore(supabase, embed_text=embedding.embed_text),
        MicroActionJournalStore(journal),
    ]
    mem = settings.memory
    missing_memory_settings = [
        name
        for name, value in (
            ("MEMORY_NEO4J_URL", mem.neo4j_url),
            ("MEMORY_NEO4J_PASSWORD", mem.neo4j_password),
            ("MEMORY_PGVECTOR_DSN", mem.pgvector_dsn),
        )
        if not value
    ]
    if mem.graph_enabled and not missing_memory_settings:
        try:
            from app.repositories.mem0_memory_store import Mem0MemoryStore

            stores.append(
                Mem0MemoryStore.from_settings(
                    llm=settings.llm, embedding=settings.embedding, memory=mem
                )
            )
            logger.info("Graph memory enabled (mem0 + Neo4j @ %s)", mem.neo4j_url)
        except Exception:
            logger.exception("Graph memory enable failed; using Supabase store only")
    elif mem.graph_enabled:
        logger.warning(
            "MEMORY_GRAPH_ENABLED set but required settings missing (%s) — graph memory off",
            ", ".join(missing_memory_settings),
        )
    return CompositeMemoryStore(*stores)


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
    app.state.place_memory_service = PlaceMemoryService(app.state.place_memory_store, llm=llm)
    app.state.cat_journal = RawCatJournal.from_settings(settings)
    logger.info("Cat journal raw graph logs: %s", app.state.cat_journal.root_dir)
    app.state.memory_store = _build_memory_store(
        settings,
        app.state.supabase,
        app.state.cat_journal,
    )
    app.state.world_state = WorldState()
    app.state.social_service = SocialService(world=app.state.world_state)
    app.state.behavior_graph = build_behavior_graph(
        llm,
        place_memory=app.state.place_memory_service,
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
        raw_journal=app.state.cat_journal,
        memory_store=app.state.memory_store,
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
