"""
Redis async client factory.

Only knows how to connect and disconnect.
Called by lifespan.py — never imported directly by routes.
"""

import ssl
import logging
import redis.asyncio as aioredis
from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_redis(settings: Settings) -> aioredis.Redis:
    """
    Build an async Redis client with a connection pool.
    Prioritizes redis_url (for production/Railway) over individual host/port settings.

    Railway Redis exposes a rediss:// URL (TLS) with a self-signed certificate.
    We disable peer-verification so the handshake succeeds without installing a
    custom CA bundle.  This is safe inside Railway's private network.
    """
    if settings.redis_url:
        url = settings.redis_url
        scheme = url.split("://")[0]
        logger.info("Connecting to Redis via REDIS_URL (scheme=%s)…", scheme)

        kwargs: dict = dict(
            decode_responses=True,
            socket_timeout=5.0,
            socket_keepalive=True,
            retry_on_timeout=True,
            health_check_interval=30,
        )

        if scheme == "rediss":
            # Railway issues self-signed TLS certs — skip verification.
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE

        return aioredis.from_url(url, **kwargs)

    logger.info(
        "Connecting to Redis via host=%s port=%d db=%d…",
        settings.redis_host, settings.redis_port, settings.redis_db,
    )
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=getattr(settings, "redis_password", None),
        decode_responses=True,
        health_check_interval=30,
    )


async def close_redis(client: aioredis.Redis) -> None:
    """Gracefully drain the connection pool."""
    if client:
        await client.aclose()
        logger.info("Redis connection closed")