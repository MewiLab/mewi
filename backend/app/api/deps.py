"""
FastAPI dependency functions.

Concurrency model
─────────────────
AgentService is now created fresh on every request so that per-request
resources (redis, supabase, agent, graph) are injected cleanly without the
race condition that arose from overwriting attributes on a shared singleton.

Cross-request state (creature buffers, last snapshot IDs) lives in
AgentServiceState, a lightweight process-scoped singleton that is created
once at module level and injected into every fresh AgentService instance.

Module-level singletons
───────────────────────
_shared_state     — AgentServiceState: holds per-creature snapshot buffers
_semantic_service — SemanticService:   stateless, cheap to share

Both are None until the first request triggers get_agent_service, at which
point they are initialised and reused for the lifetime of the process.
The deferred import inside get_agent_service matches the existing pattern in
this file and avoids any startup ordering issues.
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


# ── Process-scoped singletons ─────────────────────────────────
#
# Declared as None here; initialised on the first call to get_agent_service.
# Using None sentinels (rather than direct assignment) defers the import of
# agent_service and semantic_service until the app is fully started, which
# is consistent with the existing deferred-import pattern below.

_shared_state:     object | None = None   # AgentServiceState
_semantic_service: object | None = None   # SemanticService


# ── AgentService (per-request instance, shared state) ─────────
#
# A new AgentService is constructed on every request.
# Per-request deps (redis, supabase, agent, graph) are injected fresh, so
# concurrent requests for different creatures never overwrite each other's
# attributes.
# The _shared_state singleton carries the buffers across requests so the
# X-to-1 aggregation window is preserved between ticks.

def get_agent_service(
    redis: RedisDep,
    settings: SettingsDep,
    agent: AgentDep,
    graph: GraphDep,
    supabase: SupabaseDep,
):
    global _shared_state, _semantic_service

    from app.services.agent_service import AgentService, AgentServiceState
    from app.services.semantic_service import SemanticService

    if _shared_state is None:
        _shared_state     = AgentServiceState()
        _semantic_service = SemanticService()

    return AgentService(
        redis=redis,
        settings=settings,
        agent=agent,
        graph=graph,
        supabase=supabase,
        semantic_service=_semantic_service,  # type: ignore[arg-type]
        state=_shared_state,                 # type: ignore[arg-type]
        aggregation_limit=10,
    )


AgentServiceDep: TypeAlias = Annotated[object, Depends(get_agent_service)]
