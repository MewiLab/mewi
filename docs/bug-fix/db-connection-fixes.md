# Database Connection Issue Fix Log

## Overview

This document tracks a series of fixes related to Database/Redis connections, memory hydration, and testing infrastructure robustness. The fixes resolve functional gaps, isolate tests from real environments, and stabilize the integration testing suite.

Key areas addressed:
1. Functional gap in Agent memory hydration via DB.
2. Incomplete unit test mocks causing DB operations to hit real connections.
3. Unimplemented fixtures and test environment pollution (e.g., `.env` leaking into tests).
4. Redis decoding crashes and incorrect method calls in tests.

---

## Issue 1: Agent memory is empty on the first tick, not hydrated from DB

### Source of Issue
Although `AgentService.run_tick()` receives `creature_id`, it does not pass it to the graph state, nor does it attempt to restore the previous session's memory from DB/Redis before execution.

### Root Cause
`MemoryManager` is an in-memory ring buffer, which is empty every time the app restarts. While `hydrate_agent()` is implemented, it is only called once in the startup hook with a hardcoded ID. The actual `creature_id` is never used to trigger hydration.

### Impact
The Agent's memory is always empty during the first tick inference after a restart. The graph state lacks `creature_id`, making DB queries impossible within graph nodes.

### Fix Details
Added `_hydrate_if_empty(creature_id)` to `AgentService`. Triggered hydration before calling the graph in `run_tick`, and added `creature_id` to the graph state schema.

---

## Issue 2: `mock_redis` in unit tests did not cover commands used by MemoryCache

### Source of Issue
The `mock_redis` fixture in `tests/conftest.py` only mocked `set` and `get`, completely missing the four Redis list commands actually used by `MemoryCache`.

### Root Cause
`MemoryCache` uses `push_tick` (`rpush`, `ltrim`), `load_ticks` (`lrange`), and `clear` (`delete`). When mocked via `AsyncMock()`, these return `MagicMock`, causing unpredictable behavior.

### Impact
When `MemoryCache.load_ticks` calls `lrange`, it returns a `MagicMock` object, causing subsequent JSON parsing to crash.

### Fix Details
Added `lrange`, `rpush`, `ltrim`, and `delete` as `AsyncMock` to `mock_redis` in `tests/conftest.py`.

---

## Issue 3: `test_agent_tick_returns_200_with_action` triggered a real DB query

### Source of Issue
The agent tick test in `tests/unit/api/test_api_routes.py` only overridden `get_graph`, but not `get_agent`.

### Root Cause
The condition for `_hydrate_if_empty` is `tick_count == 0` → execute DB hydration. The test client creates a real `CreatureAgent` (`tick_count = 0`), which triggered a DB query. The mock DB returned a row without the `"perception"` field.

### Impact
Throws `KeyError: 'perception'`, causing the HTTP test to fail with a 500 error instead of the expected 200.

### Fix Details
Added a `get_agent` dependency override in the test, providing an agent with `tick_count = 1` to bypass DB hydration entirely.

---

## Issue 4: `real_settings` fixture was never implemented

### Source of Issue
The docstring in `tests/conftest.py` clearly states that integration tests use `real_*` fixtures loading credentials from `.env`, but `real_settings` was never implemented.

### Root Cause
Oversight during initial test setup.

### Impact
All tests relying on `real_settings` (unit and integration) instantly ERROR out with `fixture 'real_settings' not found`.

### Fix Details
Implemented the `real_settings` fixture in `tests/conftest.py` to load `.env` credentials dynamically, or `pytest.skip()` if credentials are missing to avoid blocking `make test`.

---

## Issue 5: `test_redis_real` (Unit) called a non-existent public method `set_status`

### Source of Issue
`tests/unit/core/test_redis_real.py` called `svc.set_status(...)`, but the corresponding method in `AgentService` is private (`_set_status`).

### Root Cause
The test used a public API naming convention, but the implementation intentionally kept it private.

### Impact
`AttributeError: 'AgentService' object has no attribute 'set_status'.`

### Fix Details
Changed `svc.set_status(` to `svc._set_status(` in `test_redis_real.py`.

---

## Issue 6: `get_status` crashed on Redis client with `decode_responses=True`

### Source of Issue
The return logic of `get_status` assumed the Redis response was always `bytes` and called `.decode()`.

### Root Cause
Tests instantiated Redis with `decode_responses=True`, making `get()` return a `str`. Calling `.decode()` on a `str` causes a crash.

### Impact
`AttributeError: 'str' object has no attribute 'decode'.`

### Fix Details
Modified `get_status` to handle both `bytes` (production) and `str` (test) environments gracefully.

---

## Issue 7: Missing `real_redis` fixture (`tests/conftest.py`)

### Source of Issue
All tests in `tests/integration/test_redis_real.py` depend on the `real_redis` fixture, but it was never defined in `conftest.py`.

### Root Cause
The test file's docstring explicitly stated "the fixture is provided by conftest.py", but the implementation was missing.

### Impact
All three integration tests failed with `fixture 'real_redis' not found`.

### Fix Details
Added the `real_redis` fixture to `tests/conftest.py`:
```python
@pytest.fixture
async def real_redis(real_settings):
    client = aioredis.from_url(
        f"redis://{real_settings.redis_host}:{real_settings.redis_port}",
        db=real_settings.redis_db,
        decode_responses=False,
    )
    yield client
    await client.aclose()
```

---

## Issue 8: Integration test calling non-existent `set_status` (`tests/integration/test_redis_real.py`)

### Source of Issue
Similar to Issue 5, two tests in the integration suite called `svc.set_status(...)`, which does not exist on `AgentService`.

### Root Cause
The method is intentionally private (`_set_status`) — it is only called internally by `run_tick`. The integration test was written with the wrong method name.

### Impact
`AttributeError: 'AgentService' object has no attribute 'set_status'.`

### Fix Details
Changed `svc.set_status(...)` → `svc._set_status(...)` in `test_set_and_get_status` and `test_ttl_is_set` (consistent with how unit tests call the same method).

---

## Issue 9: `test_valid_settings` polluted by `.env` `REDIS_HOST` (`tests/unit/core/test_config.py`)

### Source of Issue
`test_valid_settings` creates `Settings(...)` without passing `redis_host`, expecting Pydantic's model default `"localhost"`, but instead received `"127.0.0.1"` and failed.

### Root Cause
There are two sources feeding `REDIS_HOST=127.0.0.1` into Pydantic:
1. `conftest.py` calls `load_dotenv(override=True)` at module load time, injecting it into `os.environ`.
2. Pydantic `BaseSettings` reads the `.env` file directly.
`monkeypatch.delenv` only clears `os.environ`, so Pydantic's direct `.env` read still prevailed.

### Impact
Test assertions fail due to environment variable pollution.

### Fix Details
Used both `monkeypatch.delenv("REDIS_HOST", raising=False)` to clear `os.environ` and `_env_file=None` in the `Settings` instantiation to force Pydantic to skip reading `.env` for this specific test.

---

## Summary of Modified Files

| File | Type | Modification Details |
|---|---|---|
| `app/agent/schemas/state_schema.py` | Logic | Added `creature_id` field |
| `app/services/agent_service.py` | Logic | Added `_hydrate_if_empty`; `run_tick` hydrates and passes `creature_id`; `get_status` handles both `str`/`bytes` Redis return types |
| `app/workers/agent_worker.py` | Logic | Added `creature_id` to graph state |
| `tests/conftest.py` | Test Infra | Added `real_settings` and `real_redis` fixtures; filled out Redis commands for `mock_redis` |
| `tests/unit/api/test_api_routes.py` | Test Fix | Added `get_agent` override to `test_agent_tick` to avoid hitting real DB |
| `tests/unit/workers/test_agent_worker.py` | Test Fix | Changed `mock_agent.body.get_state` to `AsyncMock` |
| `tests/unit/services/test_agent_service.py` | Test Addition| Added 4 new tests to verify hydration behavior |
| `tests/unit/core/test_config.py` | Test Fix | Prevented `.env` pollution in `test_valid_settings` using `monkeypatch` and `_env_file=None` |
| `tests/unit/core/test_redis_real.py` | Test Fix | Renamed `set_status` → `_set_status` |
| `tests/integration/test_redis_real.py` | Test Fix | Renamed `set_status` → `_set_status` to align with the private method |