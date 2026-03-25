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

