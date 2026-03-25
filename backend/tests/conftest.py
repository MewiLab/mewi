"""
Root conftest — shared fixtures for ALL tests.

Markers:
  - @pytest.mark.paid   → calls real APIs (OpenAI, Supabase). Excluded by default.
  - (no marker)         → unit tests using mocks. Always safe to run.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.config import Settings


# ── Fake Settings (no real credentials) ───────────────────────

@pytest.fixture
def settings():
    """Settings with dummy values — no .env file needed."""
    return Settings(
        supabase_url="http://fake-supabase.local",
        supabase_key="fake-key",
        openai_api_key="fake-openai-key",
        redis_host="localhost",
        redis_port=6379,
        agent_status_ttl=300,
    )


# ── Mock DB clients ──────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Async Redis mock — all methods return coroutines."""
    r = AsyncMock()
    r.get.return_value = None  # default: no key → idle
    return r


@pytest.fixture
def mock_supabase():
    """
    Supabase client mock with a chainable query builder.

    Usage in tests:
        mock_supabase.table("micrologs").insert(...).execute.return_value = ...
    """
    client = MagicMock()

    # Build a chainable query builder mock
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.update.return_value = builder
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.order.return_value = builder
    builder.range.return_value = builder
    builder.limit.return_value = builder
    builder.maybe_single.return_value = builder

    # Default execute returns empty data
    builder.execute.return_value = MagicMock(data=[])

    client.table.return_value = builder
    client._builder = builder  # expose for easy assertion in tests

    return client
