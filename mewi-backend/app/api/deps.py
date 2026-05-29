from __future__ import annotations

from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from starlette.requests import HTTPConnection
from supabase import Client

from app.core.config import Settings, get_settings


SettingsDep: TypeAlias = Annotated[Settings, Depends(get_settings)]


def verify_api_key(
    connection: HTTPConnection,
    settings: SettingsDep,
) -> None:
    api_key = connection.headers.get("X-API-Key") or connection.query_params.get("api_key")
    if not api_key or api_key != settings.API_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


# Supabase 
def get_supabase(connection: HTTPConnection) -> Client:
    return connection.app.state.supabase


SupabaseDep: TypeAlias = Annotated[Client, Depends(get_supabase)]


# Redis
def get_redis(connection: HTTPConnection) -> aioredis.Redis:
    return connection.app.state.redis


RedisDep: TypeAlias = Annotated[aioredis.Redis, Depends(get_redis)]


# Behavior graph (compiled once at startup, reused per tick)
def get_behavior_graph(connection: HTTPConnection):
    return connection.app.state.behavior_graph


BehaviorGraphDep: TypeAlias = Annotated[object, Depends(get_behavior_graph)]


# AgentTickService (thin Redis queue facade) 
def get_agent_tick_service(
    connection: HTTPConnection,
    redis: RedisDep,
    settings: SettingsDep,
):
    from app.services.agent_tick.tick_service import AgentTickService

    if not hasattr(connection.app.state, "agent_tick_service"):
        connection.app.state.agent_tick_service = AgentTickService(
            redis=redis,
            settings=settings,
        )
    return connection.app.state.agent_tick_service


AgentTickServiceDep: TypeAlias = Annotated[object, Depends(get_agent_tick_service)]
