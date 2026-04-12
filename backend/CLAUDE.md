# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Package manager:** `uv` (all commands prefixed with `uv run`)

```bash
# Development (Redis in Docker, app runs natively with hot reload)
make dev

# Full Docker stack
make docker-up
make docker-down

# Testing
make test                          # unit tests (mocked, no external calls)
make test-s                        # unit tests with stdout
CONFIRM_PAID=1 make test-integration  # integration tests (needs .env + Redis)
CONFIRM_PAID=1 make test-all          # all tests

# Run a single test file
uv run pytest tests/unit/path/to/test.py -s

# Database migrations (requires deploy stack running)
make migration msg='describe change'
make migrate
```

Integration tests require `CONFIRM_PAID=1` as a safeguard since they call real external APIs. Unit tests use `pytest-env` to inject fake credentials so no `.env` is needed.

## Architecture

This is the backend for **Mewi** — an AI cat companion that runs in a Unity game. The backend is a FastAPI app that drives a LangGraph-based agent which perceives the game world, reasons with an LLM, and sends actions back to Unity.

### Agent Design: Creature = Body, Graph = Brain

The central design principle: **`CreatureAgent` is the body, LangGraph is the brain.**

- **`app/agent/creature_agent.py`** — `CreatureAgent` owns three subsystems injected at construction: `eye` (perception), `memory`, and `body` (actions). It exposes `perceive()`, `remember()`, `act()`, and `get_context()` — glue methods, no logic.
- **`app/agent/graph.py`** — `build_creature_graph()` assembles the LangGraph: `perceive → remember → reason → act → reflect`. Each node is a factory function that closes over the agent. The graph holds no agent reference in state; it's purely data-driven.
- **`app/agent/llm_provider.py`** — `LLMProvider` Protocol abstracts the LLM backend. Configured via `LLM_PROVIDER` env var (`openai`, `anthropic`, `ollama`, `openrouter`). The graph only knows the Protocol; no LLM import leaks into graph nodes.

### Request Flow

1. Unity calls `POST /api/v1/agent/tick` with a JSON payload (creature snapshot + environment snapshot)
2. `AgentService.run_tick()` invokes the compiled LangGraph
3. Graph runs: perceive → remember → reason (LLM call) → act (HTTP to Unity AgentBridge) → reflect
4. Response returns chosen action + reasoning to Unity

### Key Modules

| Path | Role |
|---|---|
| `app/main.py` | App factory — wires routers, exception handler |
| `app/core/lifespan.py` | Startup/shutdown: creates Redis, Supabase, agent, graph, workers |
| `app/core/config.py` | Pydantic Settings — `Settings`, `LLMSettings`, `EmbeddingSettings` via `get_settings()` |
| `app/api/deps.py` | FastAPI dependency aliases (`AgentDep`, `RedisDep`, `SupabaseDep`, etc.) |
| `app/agent/unity_client.py` | HTTP client that talks to Unity's AgentBridge at `UNITY_BRIDGE_URL` |
| `app/workers/` | Background workers: `AgentWorker` (autonomous tick loop), `MicrologWorker` (embedding batch) |
| `app/repositories/` | Data access: `memory_repo.py` (Supabase), `memory_cache.py` (Redis) |
| `app/services/memory_service.py` | `hydrate_agent()` (restore memory on startup), `persist_tick()` (save after each tick) |

### Infrastructure

- **Redis** — agent status cache (`thinking` / `idle`), short-term memory cache
- **Supabase** — persistent storage for creature memory, micrologs, user data
- **Unity AgentBridge** — HTTP server inside the game at `UNITY_BRIDGE_URL` (default `http://localhost:8080`) that receives actions and returns perception snapshots

### LLM Configuration

Switch providers by setting env vars in `.env`:

```
LLM_PROVIDER=openai          # default
LLM_PROVIDER=ollama          # local; sets LLM_BASE_URL=http://localhost:11434 automatically
LLM_PROVIDER=openrouter      # LLM_API_KEY=sk-or-...  LLM_MODEL=anthropic/claude-sonnet-4-5
LLM_PROVIDER=anthropic
LLM_MODEL=gpt-4-turbo        # override the model
```

### Testing Patterns

- Unit tests mock `UnityClient` via `MockUnityClient` (`tests/mock_unity_client.py`) and inject fake subsystems directly into `CreatureAgent(eye=..., memory=..., body=...)`.
- Integration tests use `@pytest.mark.paid` and need real `.env` credentials + a running Redis.
- `conftest.py` provides `agent`, `eye`, `memory`, `body`, `mock_client`, `make_unity_payload`, `make_entity` fixtures shared across all tests.
