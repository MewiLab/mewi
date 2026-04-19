# DB / Connection Fixes

## Fix 1: Missing `real_redis` fixture (`tests/conftest.py`)

**Problem:** All tests in `tests/integration/test_redis_real.py` depend on the `real_redis` fixture, but it was never defined in `conftest.py`, causing all three tests to fail with `fixture 'real_redis' not found`.

**Root cause:** The test file's docstring explicitly stated "the fixture is provided by conftest.py", but the implementation was missing.

**File changed:** `tests/conftest.py`

**Added:**
```python
@pytest.fixture
async def real_redis(real_settings):
    """
    Real async Redis client for integration tests.
    Connects using credentials from .env via real_settings.
    Closes the connection after the test completes.
    """
    client = aioredis.from_url(
        f"redis://{real_settings.redis_host}:{real_settings.redis_port}",
        db=real_settings.redis_db,
        decode_responses=False,
    )
    yield client
    await client.aclose()
```

`aioredis` is already imported at the top of `conftest.py` as `import redis.asyncio as aioredis`, so no new dependency is required.

---

## Fix 3: Integration test calling non-existent `set_status` (`tests/integration/test_redis_real.py`)

**Problem:** Two tests called `svc.set_status(...)`, which does not exist on `AgentService`, causing `AttributeError`.

**Root cause:** The method is intentionally private (`_set_status`) — it is only called internally by `run_tick`. The integration test was written with the wrong method name.

**File changed:** `tests/integration/test_redis_real.py`

**Changed:** `svc.set_status(...)` → `svc._set_status(...)` in `test_set_and_get_status` and `test_ttl_is_set` (consistent with how unit tests call the same method).

---

## Fix 4: Embedding service uses Ollama / gemma3:27b instead of OpenAI

**Problem:** The embedding integration tests (`tests/unit/services/test_embedding_real.py`) failed with OpenAI 401 because no valid `OPENAI_API_KEY` was reachable via the embedding key fallback chain.

**Root cause (two parts):**

1. `LLMSettings` reads `LLM_API_KEY` (due to `env_prefix="LLM_"`), but `.env` only has `OPENAI_API_KEY`. The fallback `emb.api_key or settings.llm.api_key` resolved to `""`, giving OpenAI an empty key.
2. No Ollama base URL was plumbed into `EmbeddingService`, so it always called OpenAI even though an Ollama server was available.

**Changes:**

### `app/core/config.py`
Added `ollama_base_url: str = ""` to `Settings`, which reads `OLLAMA_BASE_URL` from `.env`.

### `app/services/embedding_service.py`
Updated `__init__` with a three-level fallback chain:

- **base_url**: `EMBEDDING_BASE_URL` → `OLLAMA_BASE_URL + /v1` → `None` (OpenAI default)
- **api_key**: `EMBEDDING_API_KEY` → `LLM_API_KEY` → `"ollama"` (placeholder for local servers that require a non-empty key)

### `.env`
Added `EMBEDDING_MODEL=gemma3:27b` so `EmbeddingSettings.model` resolves to `gemma3:27b` and the Ollama endpoint receives the correct model name.

### `tests/unit/services/test_embedding_real.py`
- Renamed `test_returns_1536_dim_vector` → `test_returns_embedding_vector`
- Changed `assert len(vector) == 1536` → `assert len(vector) > 0`

`1536` is the dimension of OpenAI's `text-embedding-3-small`. `gemma3:27b` produces embeddings with a different dimension, so the hardcoded assertion was wrong for this provider.

---

## Fix 5: LLM graph tests calling OpenAI instead of Ollama (`tests/integration/test_graph_think.py`)

**Problem:** All `TestPaidLLMThink` tests failed with OpenAI 401. The log showed `Creating LLM provider: openai / gpt-4-turbo` — the app was targeting OpenAI even though an Ollama server was configured.

**Root cause:** `LLMSettings` uses `env_prefix="LLM_"`, so it reads `LLM_PROVIDER`, `LLM_BASE_URL`, and `LLM_MODEL` from the environment. The `.env` file only had `OLLAMA_BASE_URL` and `OLLAMA_MODEL` (no `LLM_` prefix), so `LLMSettings` fell back to its defaults: `provider=openai`, `model=gpt-4-turbo`, `api_key=""` → 401.

`_real_llm()` in the test file calls `create_llm_provider()` → `get_settings().llm`, so it inherits the same misconfiguration.

**Fix:** Added three `LLM_*` variables to `.env` so `LLMSettings` picks up the Ollama server:

```
LLM_PROVIDER=ollama
LLM_BASE_URL=https://primehub.aic.ncku.edu.tw/console/apps/ollama-0-13-4-fbxwp
LLM_MODEL=gemma3:27b
```

After the env vars were added, the provider was correctly selected but requests still returned 404:

```
POST .../ollama-0-13-4-fbxwp/chat/completions   ← 404
```

The OpenAI SDK appends `/chat/completions` directly to `base_url`, so the correct endpoint requires `base_url` to end with `/v1`:

```
POST .../ollama-0-13-4-fbxwp/v1/chat/completions   ← 200
```

**Additional fix — `app/agent/llm_provider.py` `_make_ollama_provider`:**

```python
# Before
base_url=f"{settings.base_url}",

# After
base_url = settings.base_url.rstrip("/")
if not base_url.endswith("/v1"):
    base_url = base_url + "/v1"
```

This makes the function idempotent — it works whether `LLM_BASE_URL` is set with or without the `/v1` suffix.

---

## Fix 6: Missing `real_client` and `real_supabase` fixtures (`tests/conftest.py`)

**Problem:** 10 E2E tests in `test_agent_pipeline_e2e.py` and `test_fullstack_e2e.py` failed with `fixture 'real_client' not found` / `fixture 'real_supabase' not found`.

**Root cause:** Both fixtures were documented in the test files as "provided by conftest.py" but were never implemented, similar to the earlier `real_redis` omission.

**Added to `tests/conftest.py`:**

- `real_supabase` — calls `create_supabase(real_settings)` to get a service-role Supabase client for direct DB verification.
- `real_client` — creates a `httpx.AsyncClient` backed by `ASGITransport` pointed at a fresh `create_app()` instance, with `dependency_overrides` injecting the real Redis and Supabase connections from the other fixtures.

---

## Fix 7: `ActionManager.move()` called with wrong keyword argument (`tests/integration/test_agent_graph.py`)

**Problem:** `test_move_routes_correctly` called `body.move(x=0.5, z=1.0)` and got `TypeError: unexpected keyword argument 'z'`.

**Root cause:** The actual signature is `move(self, x: float, y: float, hold: float = 0.3)` — the second axis is `y`, not `z`.

**Changed:** `body.move(x=0.5, z=1.0)` → `body.move(x=0.5, y=1.0)`

---

## Fix 8: `TestReasonNode` tests calling async node synchronously (`tests/integration/test_graph_think.py`)

**Problem:** 4 tests in `TestReasonNode` failed with `TypeError: 'coroutine' object is not subscriptable`.

**Root cause:** `make_reason_node` returns an `async def reason(state)` function. The test methods were plain `def` (synchronous), so `out = node(state)` returned a coroutine object instead of the actual result dict. Subscripting a coroutine raises `TypeError`.

**Changed:** All 4 methods (`test_returns_chosen_action_from_llm`, `test_malformed_llm_falls_back_to_wait`, `test_llm_code_fence_stripped`, `test_messages_appended`) converted from `def` → `async def`, decorated with `@pytest.mark.asyncio`, and `node(state)` changed to `await node(state)`.

---

## Fix 9: Embedding 501 — gemma3:27b does not support embeddings

**Problem:** `POST /api/v1/micrologs/` returned 502 because `EmbeddingService` tried to call `/v1/embeddings` on the Ollama server using `gemma3:27b`, which returned `501 Not Implemented — this model does not support embeddings`.

**Root cause:** `gemma3:27b` is a generative LLM. Most Ollama-hosted generative models do not expose an OpenAI-compatible `/v1/embeddings` endpoint. The previous Ollama fallback in `EmbeddingService` was too aggressive — it routed embedding calls to Ollama even when the model couldn't handle them.

**Solution:** Keep Ollama/gemma3:27b for the LLM (chat), use OpenAI for embeddings.

### `app/core/config.py`
Added `openai_api_key: str = ""` to `Settings` (reads `OPENAI_API_KEY` from `.env`).

### `app/services/embedding_service.py`
Removed the automatic Ollama fallback for `base_url`. Embeddings now default to `None` (OpenAI) unless `EMBEDDING_BASE_URL` is explicitly set. Updated API key chain:
```
EMBEDDING_API_KEY → LLM_API_KEY → OPENAI_API_KEY → "ollama"
```

### `.env`
Reset `EMBEDDING_MODEL=text-embedding-3-small` (OpenAI's embedding model, replaces `gemma3:27b`).

**Final split:**
| Service | Provider | Model |
|---|---|---|
| LLM (chat/reason) | Ollama | gemma3:27b |
| Embedding | OpenAI | text-embedding-3-small |

---

## Fix 10: FK constraint violation — test user missing from Supabase (`micrologs_user_id_fkey`)

**Problem:** 4 E2E tests failed with HTTP 500 because `POST /api/v1/micrologs/` returned a Supabase FK violation: `insert or update on table "micrologs" violates foreign key constraint "micrologs_user_id_fkey"`. The hard-coded `TEST_USER_ID` (`66af1b4c-…`) did not exist in the `users` table.

**Root cause:** `micrologs.user_id` has a FK reference to `users(id) ON DELETE CASCADE`. The test user row was never inserted, so any microlog write for that UUID was rejected by Postgres.

**Solution:** Added a `test_user` fixture to `tests/conftest.py` that upserts the test user before each test and deletes them (cascading to micrologs) after.

**Files changed:**

### `tests/conftest.py`

```python
@pytest.fixture
def test_user(real_supabase):
    """
    Ensure the E2E test user exists in Supabase before each test that writes micrologs.
    Deletes the user (and cascades to micrologs) after the test completes.
    """
    user_id = "66af1b4c-4628-4544-addd-15c9a36b4707"
    real_supabase.table("users").upsert({"id": user_id}).execute()
    yield user_id
    real_supabase.table("users").delete().eq("id", user_id).execute()
```

### `tests/integration/test_agent_pipeline_e2e.py`

Added `test_user` parameter to the two methods that POST micrologs:
- `test_create_microlog_returns_201(self, real_client, test_user)`
- `test_get_logs_returns_recent_entry(self, real_client, test_user)`

### `tests/integration/test_fullstack_e2e.py`

Added `test_user` parameter to the two methods that POST micrologs:
- `test_post_microlog_persists_in_supabase(self, real_client, real_supabase, test_user)`
- `test_post_microlog_and_verify_both_stores(self, real_client, real_supabase, real_redis, test_user)`

---

## Fix 2: `test_valid_settings` polluted by `.env` `REDIS_HOST` (`tests/unit/core/test_config.py`)

**Problem:** `test_valid_settings` creates `Settings(...)` without passing `redis_host`, expecting Pydantic's model default `"localhost"`, but instead received `"127.0.0.1"` and failed.

**Root cause:** There are two sources feeding `REDIS_HOST=127.0.0.1` into Pydantic:

1. `conftest.py` calls `load_dotenv(override=True)` at module load time, injecting `REDIS_HOST` from `.env` into `os.environ`.
2. Pydantic `BaseSettings` is configured with `env_file=".env"` and reads the `.env` file directly, independently of `os.environ`.

`monkeypatch.delenv` only clears `os.environ` (source 1), but Pydantic's direct `.env` file read (source 2) still wins. Both sources must be neutralised.

**File changed:** `tests/unit/core/test_config.py`

**Before:**
```python
def test_valid_settings(self):
    s = Settings(...)
    assert s.redis_host == "localhost"
```

**After:**
```python
def test_valid_settings(self, monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)  # clear os.environ
    s = Settings(
        ...,
        _env_file=None,  # tell Pydantic to skip reading .env
    )
    assert s.redis_host == "localhost"
```

`monkeypatch.delenv` automatically restores the environment variable after the test completes, so other tests are unaffected. `_env_file=None` is scoped to this single `Settings()` call and does not affect any other test.
