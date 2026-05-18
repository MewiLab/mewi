from __future__ import annotations

from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from supabase import Client

from app.core.config import Settings, get_settings


SettingsDep: TypeAlias = Annotated[Settings, Depends(get_settings)]

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


# Supabase 
def get_supabase(request: Request) -> Client:
    return request.app.state.supabase


SupabaseDep: TypeAlias = Annotated[Client, Depends(get_supabase)]


# Redis
def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


RedisDep: TypeAlias = Annotated[aioredis.Redis, Depends(get_redis)]


# Behavior graph (compiled once at startup, reused per tick)
def get_behavior_graph(request: Request):
    return request.app.state.behavior_graph


BehaviorGraphDep: TypeAlias = Annotated[object, Depends(get_behavior_graph)]


# AgentTickService (thin Redis queue facade) 
def get_agent_tick_service(
    request: Request,
    redis: RedisDep,
    settings: SettingsDep,
):
    from app.services.agent_tick_service import AgentTickService

    if not hasattr(request.app.state, "agent_tick_service"):
        request.app.state.agent_tick_service = AgentTickService(
            redis=redis,
            settings=settings,
        )
    return request.app.state.agent_tick_service


AgentTickServiceDep: TypeAlias = Annotated[object, Depends(get_agent_tick_service)]
