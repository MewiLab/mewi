"""
Redis async client factory.
 
Only knows how to connect and disconnect.
Called by lifespan.py — never imported directly by routes.
"""

import logging
import redis.asyncio as aioredis
from app.core.config import Settings

logger = logging.getLogger(__name__)

def create_redis(settings: Settings) -> aioredis.Redis:
    """
    Build an async Redis client with a connection pool.
    Prioritizes redis_url (for production/Railway) over individual host/port settings.
    """
    if settings.redis_url:
        logger.info("Connecting to Redis using REDIS_URL...")
        return aioredis.from_url(
            settings.redis_url,
            decode_responses=True
        )
    
    logger.info(f"Connecting to Redis at {settings.redis_host}:{settings.redis_port}...")
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )
    
async def close_redis(client: aioredis.Redis) -> None:
    """Gracefully drain the connection pool."""
    if client:
        await client.aclose()
        logger.info("Redis connection closed")