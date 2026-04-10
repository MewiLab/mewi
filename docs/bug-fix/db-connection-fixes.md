# Database Connection Issue Fix Log

## Overview

This fix involves three main aspects (along with additional minor fixes):

1. Functional gap in Agent memory hydration via DB.
2. Incomplete unit test mocks causing DB operations to hit real connections.
3. Unimplemented `real_settings` fixture causing all integration tests to ERROR.

---

## Issue 1: Agent memory is empty on the first tick, not hydrated from DB

### Source of Issue

Although `AgentService.run_tick()` receives `creature_id`, it does not pass it to the graph state, nor does it attempt to restore the previous session's memory from DB/Redis before execution.

### Root Cause

`MemoryManager` is an in-memory ring buffer, which is empty every time the app restarts. While `hydrate_agent()` is implemented (in `memory_service.py`), it is only called once in the startup hook of `lifespan.py` with a hardcoded `creature_id="cat_01"`. The actual `creature_id` passed from Unity is received in `run_tick` but is never used to trigger hydration.

### Impact

- The Agent's memory is always empty during the first tick inference after a restart, meaning the LLM context lacks historical data.
- There is no `creature_id` in the graph state, making it impossible to query the DB later within graph nodes.

### Fix Details

| File | Modification |
|---|---|
| `app/agent/schemas/state_schema.py` | Added `creature_id: str` field. |
| `app/services/agent_service.py` | Added `_hydrate_if_empty(creature_id)`; triggered hydration before calling the graph in `run_tick`; added `creature_id` to graph state. |
| `app/workers/agent_worker.py` | Added `creature_id` to graph state for consistency. |

### `_hydrate_if_empty` Logic

```text
_hydrate_if_empty(creature_id):
  tick_count > 0  →  Return directly (memory exists, running normally)
  supabase = None →  Return directly (no DB, start with empty memory)
  Otherwise       →  Call hydrate_agent(agent, supabase, redis, creature_id)
                     ├─ Cache in Redis → Use directly
                     └─ No cache in Redis → Read from Supabase and backfill Redis
```

---

## Issue 2: `mock_redis` in unit tests did not cover commands used by MemoryCache

### Source of Issue

The `mock_redis` fixture in `tests/conftest.py` only mocked `set` and `get`, completely missing the four Redis commands actually used by `MemoryCache`.

### Root Cause

`MemoryCache` (`repositories/memory_cache.py`) uses:

| Method | Corresponding Command |
|---|---|
| `push_tick` | `rpush`, `ltrim` |
| `load_ticks` | `lrange` |
| `clear` | `delete` |

When mocked via `AsyncMock()`, these automatically return another `MagicMock`, causing unpredictable behavior during iteration or `await`.

### Impact

When `_hydrate_if_empty` → `hydrate_agent` → `MemoryCache.load_ticks` calls `lrange`, because the mock isn't set up, `lrange` returns a `MagicMock` object. Subsequent calls to `json.loads(entry)` crash or return garbage data.

### Fix Details

Added the following to `mock_redis` in `tests/conftest.py`:

```python
client.lrange = AsyncMock(return_value=[])   # load_ticks: cache miss → return empty
client.rpush  = AsyncMock(return_value=1)    # push_tick
client.ltrim  = AsyncMock()                  # push_tick (trim to max size)
client.delete = AsyncMock()                  # clear
```

---

## Issue 3: `test_agent_tick_returns_200_with_action` triggered a real DB query

### Source of Issue

The agent tick test in `tests/unit/api/test_api_routes.py` only overridden `get_graph`, but not `get_agent`.

### Root Cause

The condition for `_hydrate_if_empty` is `tick_count == 0` → execute DB hydration. The FastAPI TestClient's lifespan creates a real `CreatureAgent` (`tick_count = 0`), and the `mock_db` in tests shares the same builder for all tables, where `execute()` always returns:

```python
MagicMock(data=[FAKE_ROW])
```

`FAKE_ROW` is the row schema for microlog, which lacks the `"perception"` field. When `hydrate_agent` reaches:

```python
await cache.push_tick(creature_id=creature_id, perception=row["perception"])
```

It throws `KeyError: 'perception'`, causing the entire tick to fail with a 500 error.

### Impact

The `POST /api/v1/agent/tick` test expects a 200 but actually receives a 500.

### Fix Details

Added a `get_agent` override in the test, providing `tick_count = 1` so `_hydrate_if_empty` returns directly:

```python
mock_agent = MagicMock()
mock_agent.memory.tick_count = 1          # Force _hydrate_if_empty to skip DB
mock_agent.body.available_actions = ["wait", "move"]
client.app.dependency_overrides[get_agent] = lambda: mock_agent
```

The purpose of this test is to verify that graph results can be correctly returned in the HTTP response, not to test the hydration process. Therefore, skipping hydration is semantically correct here.

---

## Issue 4: `real_settings` fixture was never implemented

### Source of Issue

Line 6 of the docstring in `tests/conftest.py` clearly states:

> Integration fixtures (`real_*`): loads real credentials from `.env`. Only used when running `make test-integration CONFIRM_PAID=1`.

However, the `real_settings` fixture itself was never implemented.

### Root Cause

Pure oversight. All tests (covering unit and integration directories) that rely on `real_settings` immediately ERROR out during pytest collection:

```text
fixture 'real_settings' not found
```

Affected test files:

- `tests/unit/core/test_supabase_connection.py`
- `tests/unit/core/test_redis_real.py`
- `tests/unit/services/test_embedding_real.py`
- `tests/integration/test_supabase_connection.py`
- `tests/integration/test_redis_real.py`
- `tests/integration/test_fullstack_e2e.py`

### Fix Details

Added the following to `tests/conftest.py`:

```python
@pytest.fixture
def real_settings():
    url    = os.environ.get("SUPABASE_URL", "")
    anon   = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    secret = os.environ.get("SUPABASE_SECRET_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not all([url, anon, secret]):
        pytest.skip("real_settings requires SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY / SUPABASE_SECRET_KEY in .env")
    return Settings(
        supabase_url=url,
        supabase_publishable_key=anon,
        supabase_secret_key=secret,
        openai_api_key=openai_key or "sk-fake",
    )
```

- If `.env` exists and credentials are complete → Create a real `Settings` object.
- If missing any credential → `pytest.skip`, which avoids red failures and doesn't block `make test`.

---

## Issue 5: `test_redis_real` called a non-existent public method `set_status`

### Source of Issue

`tests/unit/core/test_redis_real.py` called `svc.set_status(...)`, but the corresponding method in `AgentService` is the private `_set_status` (with an underscore prefix).

### Root Cause

The test was written using a public API naming convention, but the implementation intentionally kept it private (CLAUDE.md design principle: status writing should only be triggered via `run_tick` and never called externally). The naming was never aligned.

### Impact

```text
AttributeError: 'AgentService' object has no attribute 'set_status'.
Did you mean: '_set_status'?
```

### Fix Details

Changed all instances of `svc.set_status(` to `svc._set_status(` in `test_redis_real.py`. Since integration tests evaluate internal behavior, directly calling a private method is acceptable here.

---

## Issue 6: `get_status` crashed on Redis client with `decode_responses=True`

### Source of Issue

The return logic of `get_status`:

```python
return value.decode() if value else "idle"
```

`.decode()` is a method for `bytes` types. When the Redis client is instantiated with `decode_responses=True`, `get()` returns a `str` directly, and calling `.decode()` on a `str` causes a crash.

### Root Cause

The client creation in `test_redis_real.py` sets `decode_responses=True` (line 19):

```python
pool = aioredis.ConnectionPool.from_url(
    f"redis://{real_settings.redis_host}:{real_settings.redis_port}/0",
    decode_responses=True,
)
```

However, the Redis client created by the production lifespan does not have this option set, so `get()` returns `bytes`. The two scenarios behaved differently, and `get_status` only accounted for one of them.

### Impact

```text
AttributeError: 'str' object has no attribute 'decode'. Did you mean: 'encode'?
```
`test_set_and_get_status` succeeded on write but crashed on read.

### Fix Details

Modified `get_status` in `app/services/agent_service.py` to handle both return types gracefully:

```python
if not value:
    return "idle"
return value.decode() if isinstance(value, bytes) else value
```

- `bytes` (production, `decode_responses` not set) → `.decode()`
- `str` (client with `decode_responses=True`) → return directly
- `None` (key does not exist) → `"idle"`

---

## Summary of Modified Files

| File | Type | Modification Details |
|---|---|---|
| `app/agent/schemas/state_schema.py` | Logic | Added `creature_id` field |
| `app/services/agent_service.py` | Logic | Added `_hydrate_if_empty`; `run_tick` hydrates and passes `creature_id`; `get_status` handles both `str`/`bytes` Redis return types |
| `app/workers/agent_worker.py` | Logic | Added `creature_id` to graph state |
| `tests/conftest.py` | Test Infrastructure | Added `real_settings` fixture; filled out Redis commands for `mock_redis` |
| `tests/unit/api/test_api_routes.py` | Test Fix | Added `get_agent` override to `test_agent_tick` to avoid hitting real DB |
| `tests/unit/workers/test_agent_worker.py` | Test Fix | Changed `mock_agent.body.get_state` to `AsyncMock` |
| `tests/unit/services/test_agent_service.py` | Test Addition | Added 4 new tests to verify hydration behavior |
| `tests/unit/core/test_redis_real.py` | Test Fix | Renamed `set_status` → `_set_status` to align with actual method name |