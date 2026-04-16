# ADR-005: Unity Creature AI Architecture — Blackboard, Layers, and LLM Bridge

**Status:** Accepted <br>
**Date:** 2026-04-16 <br>
**Deciders:** vanilasky <br>
**Relates to:** ADR-004 (covers the Python backend side of the same agent pipeline) <br>

> **Version note:** ADR-004 documents the backend decomposition (Eye / Memory / Body / Brain).
> This ADR documents the Unity client-side counterpart: how the blackboard, layered subsumption,
> and transport adapter are structured so that LLM commands from ADR-004's backend arrive in-game
> and are arbitrated correctly against reflex and tactical layers.



## Context

Mewi's cat must feel genuinely reactive — not scripted. The AI driving it must handle three distinct time-scales simultaneously:

- **Frame-rate reflexes** (< 16 ms) — flinch from sudden sounds, break eye-contact, avoid obstacles
- **Tactical decisions** (seconds) — FSM-level choices like wander, flee, investigate, eat
- **Slow cognition** (every few seconds) — LLM-driven intent shaped by mood, memory, and context

The naive approach — one script that polls an LLM every frame and directly drives animations — fails on all three counts: too slow for reflexes, too expensive to call an LLM at 60 Hz, and impossible to extend without touching everything at once.

We also need the LLM backend to be **swappable and testable in isolation**. The Unity client should not hard-depend on a running Python server; offline / simulated mode must always work.

Three core problems to solve:

1. **How do multiple AI layers share state without coupling to each other?**
2. **How does the motor layer know what to execute when multiple layers may be issuing commands?**
3. **How does the LLM response flow back into the creature without the transport layer knowing about game state?**



## Decision

### 1. Shared state via Subsumption Blackboard

All layers communicate through a single `CreatureBlackboard` MonoBehaviour. No layer holds a direct reference to any other layer.

```
CreatureBlackboard
├── mood          (MoodModel)
├── health        (HealthModel)
├── sensorEvents  (List<SensoryEvent>)    ← written by Perception
├── playerInSight, closestPlayer          ← written by Perception
├── followTarget  (Transform)             ← written by PeriodicMind (LLM mode)
│
├── ReflexIntent   (IntentMessage?)       ← written by CreatureReflexRunner
├── TacticalIntent (IntentMessage?)       ← written by CreatureBrain
└── MindIntent     (IntentMessage?)       ← written by PeriodicMind ONLY
```

**Resolution rule (Brooks' Subsumption):** Reflex > Tactical > Mind. `ResolveActiveIntent()` checks slots in priority order. Higher layers can suppress lower ones without knowing they exist.

### 2. Layered architecture with strict ownership

```
┌──────────────────────────────────────────┐
│  CreatureController  (wires + ticks all) │
├──────────┬───────────┬───────────────────┤
│ Reflex   │ Tactical  │ Mind              │  ← write to blackboard
│ Runner   │ Brain     │ PeriodicMind      │
│          │  (FSM)    │ + AgentMindBridge │
├──────────┴───────────┴───────────────────┤
│  CreaturePerception                      │  ← writes sensors to blackboard
├──────────────────────────────────────────┤
│  CreatureMotor   (ONLY Malbers contact)  │  ← reads resolved intent, drives motor
└──────────────────────────────────────────┘
```

**Layer rules:**
- Reflex and Tactical write their own intent slot — never the other's.
- `PeriodicMind` is the **sole writer** of `MindIntent` and `followTarget`.
- `CreatureMotor` is the **sole component that touches Malbers / NavMesh / MAnimalAIControl**.
- No layer holds a reference to any other layer — all communication is through the blackboard.

### 3. AgentMindBridge — pure transport adapter

`AgentMindBridge` replaces the original `CreatureAgent` + `AgentBridge` pair. It is a pure I/O adapter: it knows the wire format, owns the HTTP transport, and produces typed `LLMIntent` objects. It never writes to the blackboard.

```
PeriodicMind.Think()
    │
    ├─ TryConsumeResponse(_pendingId, out intent)
    │       → on hit: _board.SetMindIntent(intent)   ← ONLY write, stays in PeriodicMind
    │
    └─ _pendingId = _bridge.SendTick(_board)
            │
            ├─ reads blackboard → builds TickPayload JSON (owns wire format)
            └─ POST /api/v1/agent/tick → backend LangGraph
                        │
                        └─ POST /action back to AgentMindBridge:8080
                                │
                                └─ ParseAndStore() → LLMIntent (latest wins, v1)
```

**requestId v1:** "latest wins" — any stored `LLMIntent` is consumed by the next `TryConsumeResponse()` call regardless of ID, because the backend does not yet echo the `requestId` in its `/action` callback. Strict matching is a one-line TODO once the backend echoes it.

### 4. MindMode toggle

`PeriodicMind.mode` (Inspector enum):

| Mode | Behaviour |
|---|---|
| `Simulated` | Fully local rule-based mood + intent. No network. Used in offline dev and testing. |
| `LLM` | Sends ticks to backend every `mindTickInterval` seconds. Mood decay continues locally between responses. |

The motor and reflex layers are identical in both modes — they read the blackboard regardless of how the intent was produced.

### 5. AgentBridge kept as test harness

The original `AgentBridge.cs` (direct HTTP → motor dispatch, no blackboard) is retained in `Assets/Scripts/Infrastructure/` as a raw connectivity test. It is **not** used in production. Disable it when `AgentMindBridge` is active (they share port 8080).



## File Structure

```
Assets/Scripts/
├── Creature/
│   ├── Core/
│   │   ├── CreatureController.cs     ← wires all layers, drives Update tick
│   │   ├── CreatureBlackboard.cs     ← shared state bus
│   │   ├── CreatureConfig.cs         ← tuning values (ScriptableObject)
│   │   ├── IntentMessage.cs          ← struct: intent + source + expiry + directionHint
│   │   ├── MoodModel.cs
│   │   └── HealthModel.cs
│   └── Layers/
│       ├── Perception/
│       │   └── CreaturePerception.cs ← physics sensing → blackboard.sensorEvents
│       ├── Relax/
│       │   ├── CreatureReflexRunner.cs
│       │   ├── FlinchReflex.cs
│       │   ├── GazeReflex.cs
│       │   └── AvoidanceReflex.cs
│       ├── Tactical/
│       │   └── CreatureBrain.cs      ← FSM → TacticalIntent
│       ├── Mind/
│       │   ├── PeriodicMind.cs       ← timer, mood, sole MindIntent writer
│       │   └── AgentMindBridge.cs    ← HTTP transport, snapshot builder, LLMIntent
│       └── Body/
│           └── CreatureMotor.cs      ← sole Malbers contact, reads resolved intent
├── Infrastructure/
│   └── AgentBridge.cs                ← test harness only (direct motor dispatch)
├── Semantics/
│   ├── SemanticZone.cs
│   └── SemanticCategoryConfig.cs
└── Test/
    ├── CreatureAgent.cs              ← deprecated outbound-only sender, kept for reference
    ├── CreatureMVPTest.cs
    └── AnimalControllerTest.cs
```



## Intent Vocabulary

`CreatureMotor.EnterIntent()` handles the following intent strings written to the blackboard:

| Intent | Source layer | Motor behaviour |
|---|---|---|
| `idle` | Tactical / Mind | Stop AI, default stance |
| `wander` | Tactical / Mind | Random NavMesh destination within radius |
| `flee` | Tactical / Mind | Sprint away from `DirectionHint` threat position |
| `investigate` | Tactical / Mind | Sneak toward `closestPlayer` |
| `go_to` | Mind (LLM) | `aiControl.SetDestination(DirectionHint)` |
| `follow` | Mind (LLM) | `aiControl.SetTarget(blackboard.followTarget)` |
| `flinch` | Reflex | Stop AI, trigger startle action mode |
| `eat`, `drink`, `sit`, `lie`, `sleep`, `groom`, `smell`, `alert`, `vocalize` | Mind (LLM) | Malbers Action mode (one-shot, auto-clear via `OnModeEnd`) |
| `die` | Any | Disable AI, force Death state (terminal) |



## Consequences

**Positive:**
- Reflex, tactical, and LLM layers are fully decoupled — each can be tested in isolation with a mock blackboard.
- Motor layer is a single, auditable file — all Malbers API calls live in one place.
- `MindMode.Simulated` gives a fully playable offline experience at zero cost.
- Adding a new intent is one switch-case in `CreatureMotor` — no other file changes.
- Strict layer ownership prevents race conditions on the blackboard's intent slots.
- requestId design means upgrading to strict ID matching requires changing one line.

**Negative / trade-offs:**
- Blackboard is a shared mutable object — callers must respect ownership rules (not enforced by the type system).
- `PeriodicMind` polls for a response every Think() cycle regardless of whether one is expected; adds minor overhead.
- "Latest wins" requestId matching means a very slow backend response could be silently discarded by a newer tick. Acceptable for v1; fix with strict matching once backend echoes IDs.
- `AgentMindBridge` reads the blackboard to build snapshots — breaks the pure "one writer per slot" principle for reads. Reads are safe; only writes are restricted.



## Alternatives Considered

### A. Single monolithic AI script
**Rejected.** Combining perception, cognition, and motor in one script makes LLM integration impossible to test and impossible to tune independently. Any change risks breaking all three concerns.

### B. Direct LLM → Malbers dispatch (original AgentBridge approach)
**Rejected for production.** The backend POSTing directly to Malbers input bypasses the blackboard entirely, which means reflexes can never override LLM commands. Retained as `AgentBridge.cs` for connectivity testing only.

### C. Event bus instead of blackboard
**Deferred.** An event system (C# events or UnityEvents) would eliminate polling but adds subscription lifecycle complexity. The blackboard's polling model is simple, debuggable in the Inspector, and sufficient at the current tick rates.

### D. Unity Behavior Tree (e.g. Behaviour Designer)
**Rejected.** A third-party BT asset adds a dependency and couples the AI to an editor-based authoring tool. The subsumption layering achieves the same priority logic with plain C# and is easier to modify programmatically from the LLM output.

### E. Keep CreatureAgent for outbound ticks
**Rejected.** `CreatureAgent` was a fire-and-forget POST with no response correlation. `AgentMindBridge` unifies outbound (snapshot POST) and inbound (action callback) under one transport adapter, enabling requestId correlation and clean separation from the blackboard.
