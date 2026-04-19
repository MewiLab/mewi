"""
Integration test fixtures.

Overrides the root `settings` fixture so every integration test receives
real credentials from environment variables, not the unit-test mocks.
The `init_db` fixture runs once per session to apply migration.sql before
any integration test touches the database.
"""

import asyncio
import logging

import pytest

from app.core.config import Settings
from app.core.supabase.client import create_supabase_async
from app.core.supabase.schema_manager import SupabaseSchemaManager

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Real credentials loaded from environment variables."""
    return Settings()


@pytest.fixture(scope="session", autouse=True)
def init_db(settings: Settings) -> None:
    """Apply migration.sql once before any integration test runs."""

    async def _apply() -> None:
        client = await create_supabase_async(settings)
        manager = SupabaseSchemaManager(client)
        await manager.initialize_db()

    asyncio.run(_apply())
    logger.info("Database schema initialised for integration test session")
