"""
FastAPI dependency functions.

AgentService is held as a module-level singleton so that its in-memory
creature buffers (used for semantic aggregation) survive across the
per-request dependency-injection lifecycle.  All other resources are pulled
from app.state (created in lifespan.py) and are already singletons there.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, Request
from supabase import Client

from app.core.config import Settings, get_settings
from app.agent.creature_agent import CreatureAgent

# ── Settings ──────────────────────────────────────────────────
SettingsDep: TypeAlias = Annotated[Settings, Depends(get_settings)]


# ── Supabase ──────────────────────────────────────────────────
def get_supabase(request: Request) -> Client:
    return request.app.state.supabase


SupabaseDep: TypeAlias = Annotated[Client, Depends(get_supabase)]


# ── Redis ─────────────────────────────────────────────────────
def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


RedisDep: TypeAlias = Annotated[aioredis.Redis, Depends(get_redis)]


# ── Agent (eye + memory + body) ───────────────────────────────
def get_agent(request: Request) -> CreatureAgent:
    return request.app.state.agent


AgentDep: TypeAlias = Annotated[CreatureAgent, Depends(get_agent)]


# ── Graph (compiled once at startup, reused per tick) ─────────
def get_graph(request: Request):
    return request.app.state.graph


GraphDep: TypeAlias = Annotated[object, Depends(get_graph)]


# ── AgentService (singleton — preserves creature buffers) ─────
#
# A new AgentService would lose its in-memory buffers on every request.
# The singleton pattern here ensures that snapshot buffers accumulate
# correctly across ticks until the aggregation_limit is reached.

_agent_service_singleton: object | None = None


def get_agent_service(
    redis: RedisDep,
    settings: SettingsDep,
    agent: AgentDep,
    graph: GraphDep,
    supabase: SupabaseDep,
):
    global _agent_service_singleton

    from app.services.agent_service import AgentService
    from app.services.semantic_service import SemanticService

    if _agent_service_singleton is None:
        _agent_service_singleton = AgentService(
            redis=redis,
            settings=settings,
            agent=agent,
            graph=graph,
            supabase=supabase,
            semantic_service=SemanticService(),
            aggregation_limit=10,
        )
    else:
        # Refresh request-scoped deps without discarding buffer state.
        # In practice redis/supabase/agent/graph are already singletons on
        # app.state, so these assignments are no-ops — but they guard against
        # hot-reload scenarios where app.state objects are recreated.
        svc = _agent_service_singleton  # type: ignore[assignment]
        svc._redis    = redis
        svc._supabase = supabase
        svc._agent    = agent
        svc._graph    = graph

    return _agent_service_singleton


AgentServiceDep: TypeAlias = Annotated[object, Depends(get_agent_service)]
