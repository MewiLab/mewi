"""
FastAPI dependency functions.

These pull resources from app.state (created in lifespan.py) and inject
them into route handlers, services, and repositories.
No module-level singletons — everything is explicit and testable.

TypeAlias tells Pylance these are type aliases,
not regular variables, so using them in function parameter
annotations is valid.
"""

from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, Request
from supabase import Client

from app.core.config import Settings, get_settings
from app.agent.creature_agent import CreatureAgent

# ── Settings ──────────────────────────────────────────────────
SettingsDep: TypeAlias = Annotated[Settings, Depends(get_settings)]


# ── Supabase ──────────────────────────────────────────────────
def get_supabase(request: Request, settings: SettingsDep) -> Client:
    return request.app.state.supabase


SupabaseDep: TypeAlias = Annotated[Client, Depends(get_supabase)]


# ── Redis ─────────────────────────────────────────────────────
def get_redis(request: Request, settings: SettingsDep) -> aioredis.Redis:
    return request.app.state.redis


RedisDep: TypeAlias = Annotated[aioredis.Redis, Depends(get_redis)]


# ── Agent (the creature — eye + memory + body) ────────────────
def get_agent(request: Request) -> CreatureAgent:
    return request.app.state.agent


AgentDep: TypeAlias = Annotated[CreatureAgent, Depends(get_agent)]


# ── Graph (compiled once at startup, reused per tick) ─────────
def get_graph(request: Request):
    return request.app.state.graph


GraphDep: TypeAlias = Annotated[object, Depends(get_graph)]


# ── AgentService (full: graph + agent + supabase + redis) ─────
def get_agent_service(
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
    )


AgentServiceDep: TypeAlias = Annotated[object, Depends(get_agent_service)]
