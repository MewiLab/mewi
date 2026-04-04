# ADR-004: Creature Agent Architecture — Eye / Memory / Body with External LangGraph Brain

**Status:** Accepted
**Date:** 2026-04-04
**Deciders:** vanillasky



## Context

The cat-brain agent needs to perceive a Unity 3D environment, reason about what
to do, and execute physical actions — all through an HTTP bridge to the Malbers
Animal Controller.  The initial prototype (`agent.py`) mixed LLM client setup,
perception parsing, and action dispatch into a single class, with the LangGraph
hardcoded to a weather-search example unrelated to the creature's actual behavior.

Several problems emerged:

1. **Monolithic agent** — `CreatureAgent` held an OpenAI client, a snapshot manager,
   and would eventually hold action logic.  Testing any one concern required
   instantiating the entire agent with real API keys.

2. **Graph coupled to implementation** — the LangGraph defined `call_model` and
   `search` tool nodes that had no relationship to creature perception or action.
   Replacing the graph's decision logic required rewriting the agent.

3. **No typed contracts between layers** — raw dicts flowed from Unity through
   parsing through the LLM and back.  A renamed JSON field surfaced as a silent
   `None` deep in the reasoning node instead of a validation error at the boundary.

4. **No memory** — the agent perceived one tick at a time with no history.  The LLM
   had no context about where the creature had been or what it had tried before.

5. **Action execution untestable** — HTTP calls to Unity were inline in the agent.
   Unit tests could not verify action logic without a running Unity instance.



## Decision

We decompose the agent into three subsystems using a biological metaphor, compose
them via dependency injection, and keep the LangGraph brain external to the creature.

### Architecture

```
LangGraph (brain, external)
    │
    ▼
CreatureAgent (DI container)
    ├── SnapshotManager  (eye)   — perception, read-only
    ├── MemoryManager    (memory)— temporal + spatial history
    └── ActionManager    (body)  — writes to Unity, reads schema
```

**The creature is the body; the graph is the mind.  Different minds, same body.**

### Component: Eye — `SnapshotManager` (`perception.py`)

| Responsibility | Implementation |
|----------------|----------------|
| Validate raw Unity JSON | Pydantic models (`EnvironmentSnapshot`, `CreatureSnapshot`) |
| Filter entities by relevance | Distance-based culling with tunable `relevance_radius` |
| Assess threat level | Rule-based `ThreatLevel` enum (SAFE / CAUTION / DANGER) |
| Produce typed output | `PerceptionSummary` dataclass with `.to_prompt_context()` |

**Rule:** Eye is read-only.  It never writes to Unity, never stores history, never
calls an LLM.  It answers: "what do I see right now?"

### Component: Memory — `MemoryManager` (`memory.py`)

| Responsibility | Implementation |
|----------------|----------------|
| Store perception history | Bounded `deque[PerceptionSummary]` (ring buffer, max 50 ticks) |
| Track spatial movement | `SpatialRecord` entries logged when creature moves beyond resolution |
| Answer temporal queries | `last_seen_entity(name)`, `has_visited_near(x, z)` |
| Produce typed output | `MemoryRecall` dataclass with `.to_prompt_context()` |

**Rule:** Memory accumulates but never acts.  It answers: "what have I experienced?"

### Component: Body — `ActionManager` (`action.py`)

| Responsibility | Implementation |
|----------------|----------------|
| Discover capabilities | Reads `/schema` (new) or `/actions` (legacy) at connect time |
| Execute actions | `execute(name, **kwargs) → ActionResult` via HTTP POST |
| Query world state | `get_state()`, `get_world(name)`, `get_nav(tx, tz)` |
| Expose action list for LLM | `get_actions_for_prompt()` formats registry for system prompt |

**Rule:** Body never decides.  It answers: "what can I do?" and does what it's told.

### Component: DI Container — `CreatureAgent` (`agent.py`)

| Responsibility | Implementation |
|----------------|----------------|
| Wire subsystems together | Constructor injection: `__init__(eye, memory, body)` |
| Coordinate perception → memory | `perceive()` calls eye then records to memory |
| Expose unified context | `get_context() → AgentContext` for graph consumption |
| Factory for production | `create_creature_agent(unity_url, ...)` handles wiring |

**Rule:** The agent is glue, not brains.  It coordinates subsystems but contains no
decision logic.

### Component: Brain — `LangGraph` (`graph.py`)

| Node | Reads | Writes | Calls LLM? |
|------|-------|--------|-------------|
| `perceive` | `raw_payload` | `perception`, `perception_error` | No |
| `remember` | (agent memory) | `memory_context` | No |
| `reason` | `perception`, `memory_context`, `available_actions` | `chosen_action`, `reasoning`, `messages` | **Yes** |
| `act` | `chosen_action` | `action_result` | No |
| `reflect` | `action_result`, `reasoning` | `messages` | No |

**Graph flow:**
```
perceive → remember → reason → act → reflect → END
    │                    │
    └──[error]──► act    └──[wait]──► END
```

**Rule:** The graph does not own the agent.  It receives a `CreatureAgent` reference
via closure.  The agent instance is never stored in graph state (state must be
serializable).  Only the `reason` node calls an LLM; every other node is deterministic.

### State Contract — `AgentGraphState` (`state.py`)

A `TypedDict` with explicit channels per node.  Each node reads its input channels
and writes its output channels.  No node reaches into another node's concerns.  The
`messages` channel uses `Annotated[list, operator.add]` so nodes append rather than
overwrite.

### Schema-Driven Action Discovery

`ActionManager.connect()` reads Unity's `/schema` endpoint at startup and populates
an internal registry of `ActionSchema` objects.  Falls back to the legacy `/actions`
endpoint if `/schema` is not yet implemented.  This means:

- Adding a Malbers button in Unity → Python sees it on next connect
- Renaming an action → Python adapts automatically
- The LLM receives the action list via `get_actions_for_prompt()` in the system prompt

The schema format is intentionally aligned with MCP tool definitions (name +
inputSchema + description) so that future migration to a full MCP server requires
zero logic changes.



## Test Strategy

| Test file | What it covers | Mock strategy |
|-----------|---------------|---------------|
| `test_perception.py` | Validation, filtering, threat assessment | Synthetic JSON payloads |
| `test_memory.py` | Ring buffer, spatial logging, entity recall | Synthetic `PerceptionSummary` objects |
| `test_action.py` | Schema loading, execute routing, move/stop | `httpx.MockTransport` |
| `test_agent.py` | Coordination: perceive→memorize, get_context | Mock eye + memory + body |
| `test_graph.py` | Node outputs, conditional routing, end-to-end | Mock agent + mock LLM |

Every subsystem is testable in isolation because every dependency is injected.
No test requires a running Unity instance or real API keys.



## Consequences

**Positive:**
- Each subsystem (eye, memory, body) can be developed, tested, and iterated
  independently.  Perception improvements don't risk breaking action execution.
- The graph can be swapped entirely — reactive graph, planning graph, scripted
  behavior tree — without modifying the creature.
- Internal C# code in Unity can call the same capability layer (via the dispatcher)
  that Python calls via HTTP.  Same actions, same semantics, different transports.
- Memory gives the LLM temporal context ("I tried jumping there and failed") which
  the previous stateless design could not provide.
- Schema discovery makes the Python ↔ Unity contract self-maintaining.

**Negative / trade-offs:**
- More files than the monolithic prototype (6 agent files vs 2).
- The `PerceptionSummary → dict → state channel → LLM prompt` serialization chain
  has multiple conversion steps.  Each step is explicit and typed, but it is more
  code than passing raw dicts.
- Memory is in-process only.  If the FastAPI server restarts, memory is lost.
  Future work: persist to Redis for cross-session memory.
- The LLM sees a text-formatted action list, not structured tool definitions.
  Future work: use LangChain tool binding once the action schema is stable.



## Alternatives Considered

### A. Keep the monolithic CreatureAgent with embedded LLM client
**Rejected.** Untestable without real API keys.  Cannot swap the decision-making
strategy without rewriting the agent.

### B. Use LangChain AgentExecutor instead of LangGraph
**Rejected.** AgentExecutor is a single-loop agent that doesn't support the
perceive → remember → reason → act → reflect pipeline.  LangGraph's explicit
state channels match our multi-phase architecture.

### C. Put the LLM inside the CreatureAgent
**Rejected.** This couples the reasoning strategy to the creature's physical
capabilities.  A creature should be operable by a scripted controller (no LLM)
during development and testing.

### D. Use MCP as the transport protocol now
**Deferred.** MCP requires additional infrastructure (MCP server, JSON-RPC transport).
The current HTTP + schema discovery gives 80% of MCP's benefit (self-describing
capabilities, decoupled callers) with zero new dependencies.  When the action schema
stabilizes, wrapping the dispatcher as an MCP server is a one-day migration with no
logic changes.

### E. Persist memory to database from day one
**Deferred.** In-memory `deque` is sufficient for the current single-session use case.
Adding Redis or Supabase persistence is a `MemoryManager` implementation swap — the
interface and all callers remain unchanged.
