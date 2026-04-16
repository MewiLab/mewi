# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Mewi** is a Unity game about forming emotional bonds with stray cats. The cat is controlled by an AI agent — not scripted behavior — so player interactions feel genuinely reactive. The repo has two major components:

- `frontend/app/` — Unity 3D game client (C#)
- `backend/` — FastAPI + LangGraph AI agent server (Python)

## Backend Commands

All commands run from `backend/`:

```bash
make dev              # Start Redis in Docker + FastAPI with hot reload (daily workflow)
make docker-up        # Full stack in Docker (pre-deploy smoke test)
make docker-down      # Stop Docker stack

make test             # Unit tests (mocked, free)
make test-s           # Unit tests with stdout
make test-integration # Integration tests — requires .env + Redis + CONFIRM_PAID=1
make test-all         # All tests — requires CONFIRM_PAID=1

make migration msg='describe change'  # Generate Alembic migration
make migrate                          # Apply migrations (needs Docker stack running)
```

Run a single test file:
```bash
cd backend && uv run pytest tests/unit/path/to/test_file.py -s
```

## Backend Architecture

**Stack**: FastAPI · LangGraph · LiteLLM · Supabase (PostgreSQL) · Redis

```
backend/app/
  main.py              # create_app() — wires lifespan, exception handlers, routers
  core/
    lifespan.py        # Startup/shutdown (Redis, Supabase connections)
    config.py          # Settings (pydantic-settings, reads .env)
    supabase.py        # Supabase client
  api/routes/
    agent_router.py    # POST /api/v1/agent/tick  — receives game snapshot, runs LangGraph
    micrologs_router.py
    assets_router.py
  agent/               # LangGraph graph definition and node implementations
  models/              # Pydantic data models (Creature, Microlog, etc.)
  repositories/        # DB access layer (Supabase queries)
  services/            # Business logic
  workers/
    agent_tasks.py     # Background task runner for agent pipeline
```

The agent pipeline (LangGraph): **perceive → remember → reason → act → reflect**. On each `/agent/tick` call the Unity client sends a full perception snapshot; the backend runs the graph and issues action commands back to Unity via `AgentMindBridge` (HTTP on port 8080).

## Unity Client Architecture

The Unity project is at `frontend/app/`. The cat uses a **layered subsumption architecture** — all layers communicate through `CreatureBlackboard` and are wired by `CreatureController`. No layer holds a direct reference to any other layer.

See [ADR-001](frontend/docs/decisions/ADR-001-unity-creature-ai-architecture.md) for the full architecture decision record.

### Components

| Component | Layer | Responsibility |
|---|---|---|
| `CreatureBlackboard` | Core | Shared data bus — mood, health, perception events, intent slots |
| `CreaturePerception` | Perception | Physics-based sensing, writes `sensorEvents` to blackboard |
| `CreatureReflexRunner` | Reflex | Frame-rate reflexes (flinch, gaze, avoidance) — writes `ReflexIntent` |
| `CreatureBrain` | Tactical | FSM — reads blackboard conditions, writes `TacticalIntent` |
| `PeriodicMind` | Mind | Slow timer loop; sole writer of `MindIntent`; runs `Simulated` or `LLM` mode |
| `AgentMindBridge` | Mind | Pure transport — builds snapshots from blackboard, POSTs to backend, receives LLM responses |
| `CreatureMotor` | Body | **Only** component that touches Malbers / NavMesh; reads `ResolveActiveIntent()` |
| `CreatureController` | Core | Wires all layers via `Init()`, drives the `Update` tick order |
| `AgentBridge` | Infrastructure | **Test harness only** — raw HTTP → direct motor dispatch, no blackboard |

**Script locations**: `Assets/Scripts/Creature/` (layered), `Assets/Scripts/Infrastructure/` (test harness), `Assets/Scripts/Test/` (deprecated/test-only files)

### Intent Priority (Subsumption)

`CreatureBlackboard.ResolveActiveIntent()` resolves: **Reflex > Tactical > Mind**

Higher-priority layers suppress lower ones without any direct coupling.

### Data Flow (LLM mode)

```
1. CreaturePerception.Tick()
      → writes sensorEvents, playerInSight, closestPlayerDist to blackboard

2. PeriodicMind fires on timer (every mindTickInterval seconds)
      → checks AgentMindBridge.TryConsumeResponse() for a pending LLM reply
           → on hit: _board.SetMindIntent(intent)   ← only place MindIntent is written
      → calls AgentMindBridge.SendTick(_board)
           → bridge reads blackboard, builds TickPayload JSON
           → POST /api/v1/agent/tick to backend

3. Backend runs LangGraph (perceive → remember → reason → act → reflect)
      → POST /action back to AgentMindBridge:8080

4. AgentMindBridge stores response as LLMIntent (latest-wins, v1)

5. CreatureMotor.Tick() reads ResolveActiveIntent()
      → Reflex > Tactical > Mind priority applied
      → drives MAnimalAIControl (go_to, follow, wander) or Malbers Action mode (sit, eat, …)
```

**MindMode** (set in Inspector on `PeriodicMind`):
- `Simulated` — fully local rule-based mood + intent; no network
- `LLM` — sends to backend; local mood decay continues between ticks

### Intent Vocabulary (handled by CreatureMotor)

| Intent | Behaviour |
|---|---|
| `idle` | Stop AI, default stance |
| `wander` | Random NavMesh point within radius |
| `flee` | Sprint away from `DirectionHint` threat |
| `investigate` | Sneak toward `closestPlayer` |
| `go_to` | `aiControl.SetDestination(DirectionHint)` — specific world position |
| `follow` | `aiControl.SetTarget(blackboard.followTarget)` — track a named object |
| `flinch` | Stop AI, trigger startle action mode (reflex) |
| `sit`, `eat`, `drink`, `sleep`, `groom`, `vocalize`, … | Malbers Action mode (one-shot) |
| `die` | Terminal — disable AI, force Death state |

## API Contract (Unity ↔ Backend)

**Unity → Backend** `POST /api/v1/agent/tick`:
```json
{
  "requestId": "a3f1b2c9",
  "time": 12.4,
  "self": { "x": 0, "y": 0, "z": 0, "rotY": 45, "playerInSight": true, "closestPlayerDist": 2.1 },
  "mood": { "fear": 0.1, "trust": 0.4, "curiosity": 0.6, "social": 0.3, "energy": 0.8 },
  "health": { "hunger": 0.2 },
  "entities": [{ "type": "Visual", "label": "Player", "category": "player", "intensity": 0.9, "px": 1, "py": 0, "pz": 2 }]
}
```

**Backend → Unity** `POST localhost:8080/action`:

**Navigation commands (routed through `MAnimalAIControl` + NavMesh via CreatureMotor):**
```json
{ "action": "go_to", "x": 10.0, "y": 0.0, "z": 5.0 }
{ "action": "follow", "target": "Player" }
{ "action": "wander" }
{ "action": "stop" }
{ "action": "wait" }
```

**Action / expression commands (routed through Malbers Action mode):**
```json
{ "action": "sit" }
{ "action": "eat" }
{ "action": "vocalize" }
```

Named targets available to `follow`: any key registered in `AgentMindBridge.namedTargets` (e.g. `"Player"`, `"FoodBowl"`, `"HomeArea"`).

**`GET /state` response** (motor state only — cognitive state comes via `/agent/tick`):
```json
{
  "posX": 0, "posY": 0, "posZ": 0, "rotY": 45,
  "activeState": "Locomotion", "activeStance": "0",
  "grounded": true, "speed": 1.2, "sprint": false,
  "aiActive": true, "hasArrived": false,
  "remainingDist": 4.2, "currentTarget": "Player"
}
```

## Third-Party Assets (Unity)

- **Malbers Animation Controller** — animal locomotion and state machine; `MAnimal`, `MInputLink`, `MInputAction`, `MAnimalAIControl` are its core types. **`CreatureMotor` is the only script that calls Malbers API directly.**
- **LeartesStudios** — environment/scene assets

### Malbers: AI / NPC Movement System

`MAnimalAIControl` + Unity `NavMeshAgent` is Malbers' built-in NPC locomotion layer. It handles pathfinding, slowing near targets, off-mesh links, and waypoint chains. All navigation commands from the LLM are routed through this layer by `CreatureMotor`.

**Key API used by `CreatureMotor`:**

| Method | Effect |
|---|---|
| `SetDestination(Vector3 pos)` | Navigate to world position |
| `SetTarget(Transform t, true)` | Track a moving target |
| `Stop()` | Disable agent, stop animal |
| `Active` property | Enable/disable AI layer |

**Key read-only state:**

| Property | Meaning |
|---|---|
| `HasArrived` | Reached destination |
| `RemainingDistance` | Distance to destination |
| `Target` | Current target Transform |

Source: `Assets/Malbers Animations/Common/Scripts/Animal Controller/MAnimalAIControl.cs` (namespace: `MalbersAnimations.Controller.AI`)

### Malbers: Reading Animal State

```csharp
MAnimal animal = GetComponent<MAnimal>();
string stateName = animal.ActiveStateID.name;   // e.g. "Idle", "Locomotion", "Fall"
```

Built-in state names: `Idle`, `Locomotion`, `Fall`, `Jump`, `Climb`, `Death`, `Fly`, `Swim`, `UnderWater`, `Slide`.

## Environment Setup

Backend requires a `.env` file in `backend/` with Supabase credentials, Redis URL, and LLM API keys. See `backend/app/core/config.py` for the full list of required settings.

Integration tests make real LLM API calls — always set `CONFIRM_PAID=1` explicitly to avoid accidental charges.

## Git LFS

Git LFS is configured for large Unity assets (`.fbx`, `.png`, etc.).
