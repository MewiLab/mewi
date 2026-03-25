"""
Redis async client factory.
 
Only knows how to connect and disconnect.
Called by lifespan.py — never imported directly by routes.
"""

import logging

import redis.asyncio as aioredis

from app.core.config import Settings

logger = logging.getLogger(__name__)

def create_redis(settings: Settings) -> aioredis:
    """Build an async Redis client with a connection pool."""
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )
    
async def close_redis(client: aioredis.Redis) -> None:
    """Gracefully drain the connection pool."""
    await client.aclose()
    logger.info("Redis connection closed")