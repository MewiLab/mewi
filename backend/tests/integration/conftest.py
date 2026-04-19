"""
Shared fixtures for all integration tests.

real_settings  — builds Settings() from the live environment (CI secrets or
                 local .env loaded by the root conftest).
apply_db_schema — session-scoped autouse fixture that runs migration.sql once
                  before any integration test, preventing "table not found" errors.
"""

import pytest
import pytest_asyncio

from app.core.config import Settings
from app.core.supabase.client import create_supabase_async
from app.core.supabase.schema_manager import SupabaseSchemaManager


@pytest.fixture(scope="session")
def real_settings() -> Settings:
    """Load settings from the real environment (GitHub Actions secrets / .env)."""
    return Settings()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def apply_db_schema(real_settings: Settings) -> None:
    """Apply migration.sql once per session so all tables exist before tests run."""
    client = await create_supabase_async(real_settings)
    await SupabaseSchemaManager(client).initialize_db()
