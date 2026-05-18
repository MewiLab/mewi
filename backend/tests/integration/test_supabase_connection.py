"""
Integration test: verify Supabase connection with real credentials.

Marked @paid — only runs with `make test-integration CONFIRM_PAID=1`.
Requires SUPABASE_URL and SUPABASE_KEY in .env.
"""

import pytest
import httpx

from app.core.supabase import create_supabase


@pytest.mark.paid
class TestSupabaseConnection:
    def test_client_factory_creates_valid_client(self, real_settings):
        """Verify our factory produces a working Supabase client."""
        client = create_supabase(real_settings)
        assert client is not None

    def test_can_query_users_table(self, real_settings):
        """Smoke test: SELECT from users should not throw."""
        client = create_supabase(real_settings)
        try:
            response = client.table("users").select("*").limit(1).execute()
        except httpx.ConnectError as exc:
            pytest.skip(f"Supabase unreachable (DNS/network): {exc}")
        assert isinstance(response.data, list)

    def test_can_query_micrologs_table(self, real_settings):
        """Smoke test: SELECT from micrologs should not throw."""
        client = create_supabase(real_settings)
        try:
            response = client.table("micrologs").select("id").limit(1).execute()
        except httpx.ConnectError as exc:
            pytest.skip(f"Supabase unreachable (DNS/network): {exc}")
        assert isinstance(response.data, list)
