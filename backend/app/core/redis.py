"""
Redis async client factory.

Only knows how to connect and disconnect.
Called by lifespan.py — never imported directly by routes.
"""

import logging
import ssl
import urllib.parse

import redis.asyncio as aioredis

from app.core.config import Settings

logger = logging.getLogger(__name__)


def _redact_url(url: str) -> str:
    """Mask the password in a Redis URL before logging."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.password:
            safe_netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
            return parsed._replace(netloc=safe_netloc).geturl()
    except Exception:
        pass
    return url


def create_redis(settings: Settings) -> aioredis.Redis:
    """
    Build an async Redis client with a connection pool.
    Prioritizes REDIS_URL (Railway / production) over individual host/port settings.

    Handles both redis:// and rediss:// (TLS) URLs.
    Note: socket_keepalive is intentionally omitted — it requires platform-specific
    socket_keepalive_options in redis>=5 and can cause silent connection failures.
    """
    if settings.redis_url:
        url = settings.redis_url
        logger.info("Redis: connecting via REDIS_URL → %s", _redact_url(url))

        kwargs: dict = dict(
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )

        # Railway may issue rediss:// (TLS) URLs with self-signed certificates.
        if url.startswith("rediss://"):
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl_context"] = ssl_ctx
            logger.info("Redis: TLS URL detected — certificate verification disabled")

        return aioredis.from_url(url, **kwargs)

    logger.info(
        "Redis: connecting via host %s:%s db=%s",
        settings.redis_host,
        settings.redis_port,
        settings.redis_db,
    )
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=True,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=True,
    )


async def close_redis(client: aioredis.Redis) -> None:
    """Gracefully drain the connection pool."""
    if client:
        await client.aclose()
        logger.info("Redis connection closed")