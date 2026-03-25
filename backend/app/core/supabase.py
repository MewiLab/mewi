"""
Supabase client factory.
 
Only knows how to connect.
Called by lifespan.py — never imported directly by routes.
"""

import logging

from supabase import Client, create_client

from app.core.config import Settings

logger = logging.getLogger(__name__)

def create_supabase(settings: Settings) -> Client:
    client = create_client(settings.supabase_key, settings.supabase_url)
    logger.info("Supabase client created")
    return client