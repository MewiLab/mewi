"""
FastAPI dependency functions.

These pull resources from app.state (created in lifespan.py) and inject
them into route handlers, services, and repositories.
No module-level singletons — everything is explicit and testable.
"""

from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Request
from supabase import Client

from app.core.config import Settings, get_settings


# ── Settings ──────────────────────────────────────────────────
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ── Supabase ──────────────────────────────────────────────────
def get_supabase(request: Request) -> Client:
    return request.app.state.supabase


SupabaseDep = Annotated[Client, Depends(get_supabase)]


# ── Redis ─────────────────────────────────────────────────────
def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
