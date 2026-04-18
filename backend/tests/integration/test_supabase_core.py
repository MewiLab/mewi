import pytest
import asyncio
from httpx import Timeout
from supabase._async.client import AsyncClient

from app.core.config import Settings
from app.core.supabase.client import create_supabase_async
from app.core.supabase.schema_manager import SupabaseSchemaManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def real_settings() -> Settings:
    """
    Load settings from the real .env.
    conftest.py calls load_dotenv(override=True) at import time,
    so real credentials are already in os.environ when this runs.
    """
    return Settings()


# ── Test 1: Async client factory ──────────────────────────────────────────────

@pytest.mark.paid
class TestCreateSupabaseAsync:
    async def test_returns_non_none_client(self, real_settings):
        """Factory should return a connected AsyncClient."""
        client = await create_supabase_async(real_settings)
        assert client is not None

    async def test_can_select_from_users(self, real_settings):
        """Smoke-test: SELECT against the users table should not raise."""
        client = await create_supabase_async(real_settings)
        response = await client.table("users").select("id").limit(1).execute()
        assert isinstance(response.data, list)


# ── Test 2: Schema manager ────────────────────────────────────────────────────

@pytest.mark.paid
class TestSupabaseSchemaManager:
    async def test_initialize_db_succeeds(self, real_settings):
        """initialize_db() should apply the schema without raising."""
        client = await create_supabase_async(real_settings)
        manager = SupabaseSchemaManager(client)
        await manager.initialize_db()  # raises on failure

    async def test_users_table_exists_after_schema_apply(self, real_settings):
        """After initialize_db(), querying users must return a valid response."""
        client = await create_supabase_async(real_settings)
        await SupabaseSchemaManager(client).initialize_db()
        response = await client.table("users").select("id").limit(1).execute()
        assert isinstance(response.data, list)

    async def test_micrologs_table_exists_after_schema_apply(self, real_settings):
        """After initialize_db(), querying micrologs must return a valid response."""
        client = await create_supabase_async(real_settings)
        await SupabaseSchemaManager(client).initialize_db()
        response = await client.table("micrologs").select("id").limit(1).execute()
        assert isinstance(response.data, list)


# ── Test 3: adapt_unity_payload (pure — no network) ───────────────────────────

class TestAdaptUnityPayload:
    def test_maps_keys_according_to_mapping(self):
        payload = {"pos_x": 1.0, "pos_y": 2.0, "entity_name": "Dog"}
        mapping = {"pos_x": "position_x", "pos_y": "position_y", "entity_name": "name"}
        result = SupabaseSchemaManager.adapt_unity_payload(payload, mapping)
        assert result == {"position_x": 1.0, "position_y": 2.0, "name": "Dog"}

    def test_empty_payload_returns_empty_dict(self):
        result = SupabaseSchemaManager.adapt_unity_payload({}, {"a": "b"})
        assert result == {}

    def test_missing_key_in_mapping_passes_through_unchanged(self):
        """Keys absent from the mapping should survive as-is."""
        payload = {"known": "val", "unmapped": "other"}
        mapping = {"known": "db_col"}
        result = SupabaseSchemaManager.adapt_unity_payload(payload, mapping)
        assert result == {"db_col": "val", "unmapped": "other"}

    def test_empty_mapping_returns_payload_unchanged(self):
        payload = {"a": 1, "b": 2}
        result = SupabaseSchemaManager.adapt_unity_payload(payload, {})
        assert result == {"a": 1, "b": 2}

    def test_both_empty(self):
        result = SupabaseSchemaManager.adapt_unity_payload({}, {})
        assert result == {}

    def test_value_types_preserved(self):
        """Mapping must not coerce types."""
        payload = {"count": 42, "flag": True, "score": 3.14, "label": None}
        mapping = {"count": "n", "flag": "active", "score": "rating", "label": "tag"}
        result = SupabaseSchemaManager.adapt_unity_payload(payload, mapping)
        assert result == {"n": 42, "active": True, "rating": 3.14, "tag": None}

@pytest.mark.paid
async def test_unity_to_supabase_full_flow(real_settings):
    client = await create_supabase_async(real_settings)
    
    client.postgrest.timeout = 60
    
    manager = SupabaseSchemaManager(client)
    
    await manager.initialize_db()
    
    try:
        await client.rpc("exec_sql", {"query": "NOTIFY pgrst, 'reload schema';"}).execute()
    except Exception:
        pass
        
    await asyncio.sleep(1.5)
    
    user_res = await client.table("users").select("id").limit(1).execute()
    
    if not user_res.data:
        user_new = await client.table("users").insert({"aura": "test_user"}).execute()
        target_user_id = user_new.data[0]["id"]
    else:
        target_user_id = user_res.data[0]["id"]

    raw_unity_data = {
        "userId": target_user_id, 
        "posX": 10.5, 
        "posY": 0.0, 
        "posZ": -5.2
    }
    
    mapping = {"posX": "pos_x", "posY": "pos_y", "posZ": "pos_z", "userId": "user_id"}
    db_payload = manager.adapt_unity_payload(raw_unity_data, mapping)
    
    result = await client.table("perception_snapshots").insert(db_payload).execute()
    
    assert len(result.data) == 1
    assert result.data[0]["pos_x"] == 10.5
    assert result.data[0]["user_id"] == target_user_id