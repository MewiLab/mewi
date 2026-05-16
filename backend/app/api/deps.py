"""
FastAPI dependency functions.

Concurrency model
─────────────────
AgentService is created fresh on every request so that per-request resources
(redis, supabase, agent, graph) are injected cleanly.  Concurrent requests for
different creatures never share mutable per-request state.

Process-scoped singletons are initialised once in lifespan.py and read from
app.state — no module-level globals, no lazy-init guards, no `global` keyword.

  app.state.agent_state      — AgentServiceState  (per-creature locks + snapshot IDs)
  app.state.semantic_service — SemanticService     (narrative + embedding generation)
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from supabase import Client

from app.core.config import Settings, get_settings
from app.agent.creature_agent import CreatureAgent

# ── Settings ──────────────────────────────────────────────────────────────────
SettingsDep: TypeAlias = Annotated[Settings, Depends(get_settings)]


# ── API Key auth ───────────────────────────────────────────────────────────────
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    api_key: Annotated[str | None, Depends(_api_key_header)],
    settings: SettingsDep,
) -> None:
    if not api_key or api_key != settings.API_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


# ── Supabase ──────────────────────────────────────────────────────────────────
def get_supabase(request: Request) -> Client:
    return request.app.state.supabase


SupabaseDep: TypeAlias = Annotated[Client, Depends(get_supabase)]


# ── Redis ─────────────────────────────────────────────────────────────────────
def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


RedisDep: TypeAlias = Annotated[aioredis.Redis, Depends(get_redis)]


# ── Agent (eye + memory + body) ───────────────────────────────────────────────
def get_agent(request: Request) -> CreatureAgent:
    return request.app.state.agent


AgentDep: TypeAlias = Annotated[CreatureAgent, Depends(get_agent)]


# ── Graph (compiled once at startup, reused per tick) ────────────────────────
def get_graph(request: Request):
    return request.app.state.graph


GraphDep: TypeAlias = Annotated[object, Depends(get_graph)]


# ── AgentService (per-request instance, app-state singletons) ────────────────
def get_agent_service(
    request: Request,
    redis: RedisDep,
    settings: SettingsDep,
    agent: AgentDep,
    graph: GraphDep,
    supabase: SupabaseDep,
):
    from app.services.agent_service import AgentService

    return AgentService(
        redis=redis,
        settings=settings,
        agent=agent,
        graph=graph,
        supabase=supabase,
        semantic_service=request.app.state.semantic_service,
        state=request.app.state.agent_state,
        aggregation_limit=settings.BUFFER_FLUSH_THRESHOLD,
    )


AgentServiceDep: TypeAlias = Annotated[object, Depends(get_agent_service)]
