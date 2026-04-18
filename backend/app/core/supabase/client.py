"""
Supabase client factories — sync and async.

Called by lifespan.py; never imported directly by routes.
"""

import logging

from supabase import Client, ClientOptions, create_client
from supabase import acreate_client, AsyncClient

from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_supabase(settings: Settings) -> Client:
    options = ClientOptions(
        postgrest_client_timeout=settings.supabase_timeout,
        storage_client_timeout=settings.supabase_timeout,
    )
    client = create_client(
        settings.supabase_url,
        settings.supabase_secret_key,
        options=options,
    )
    logger.info("Supabase sync client created with Service Role privileges")
    return client


async def create_supabase_async(settings: Settings) -> AsyncClient:
    options = ClientOptions(
        postgrest_client_timeout=settings.supabase_timeout,
        storage_client_timeout=settings.supabase_timeout,
    )
    client = await acreate_client(
        settings.supabase_url,
        settings.supabase_secret_key,
        options=options,
    )
    logger.info("Supabase async client created with Service Role privileges")
    return client
