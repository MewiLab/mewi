"""
Supabase client factory.

Only knows how to connect.
Called by lifespan.py — never imported directly by routes.

Note: The Supabase Python SDK has moved timeout/verify config into the HTTP client layer.
"""

import logging

from supabase import Client, create_client, ClientOptions

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
        options=options
    )
    logger.info("Supabase client created with Service Role privileges")
    return client