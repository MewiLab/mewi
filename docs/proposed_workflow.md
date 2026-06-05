# Proposed Workflow: Backend-Owned World, Unity-As-Renderer

This is the one-page summary of [ADR-010](decisions/ADR-010-backend-owned-world-and-social-chat.md).
[current_workflow.md](current_workflow.md) describes the system as it ships today.

## Why change shape

Today the truth of the world is split: Unity owns geometry and confirms eat /
arrive ([ADR-008](decisions/ADR-008-goal-event-bus-plan-step-feedback.md)),
Python owns memory ([ADR-009](decisions/ADR-009-python-owned-cat-memory.md)),
and place statistics ([ADR-006](decisions/ADR-006-place-memory-reflect-loop.md)).
That worked for one cat. It does not generalize to "two cats are in the same
room and noticed each other" because no single party sees both cats inside one
tick.

Because Unity already guarantees that every plan terminates
([ADR-005](decisions/ADR-005-movement)), we can collapse the world into Python.
Unity becomes the renderer plus a thin advisory channel for `reason` strings.

## Old shape vs new shape

```mermaid
flowchart LR
    subgraph Old["Today"]
      UA[Unity:<br/>geometry + GoalEventBus<br/>(world truth for eat/arrive)]
      PA[Python:<br/>per-cat LangGraph + memory]
      UA -->|snapshot + report| PA
      PA -->|plan steps| UA
    end

    subgraph New["ADR-010 target"]
      UB[Unity:<br/>animation + NavMesh<br/>reports reason strings]
      PB[Python:<br/>WorldState + SocialRoom + LangGraph + memory]
      UB -->|coarse snapshot + reason| PB
      PB -->|plan steps + dialogue| UB
    end
```

## What lives where

| Concern | Where |
|---|---|
| NavMesh, animation, collision | Unity |
| Cat approximate position (zone + xy) | Python `WorldState` |
| Object inventory (fish portions) | Python `EdibleStore` (Unity has a cosmetic gate) |
| `eat` / `go_to` outcome | Python, refined by Unity `reason` |
| Cat-cat encounter, dialogue, relationship | Python `SocialRoom` |
| Cat memory (raw + STM) | Python (unchanged from ADR-009) |
| Player attachment events | C# logger → Python (unchanged from ADR-007) |

## New tick (one cat ticks → world + social step)

```mermaid
sequenceDiagram
    autonumber
    participant U as Unity (cat A)
    participant W as WorldState
    participant S as SocialRoom
    participant G as LangGraph (slow + fast mind)
    participant Memory as Memory

    U->>W: tick snapshot + previous plan report
    W->>W: update presence A; record step events
    W->>S: probe co-located cats
    alt cats co-located in zone
        S->>S: moderator picks speaker, applies effects
        S-->>W: relationship + mood deltas
    end
    W->>G: world view + social inbox + place memory
    G-->>W: intent + plan steps
    W->>Memory: write raw turn + STM
    W-->>U: plan { actions, dialogue }
```

The cat whose snapshot arrived is the only cat whose plan changes this turn.
Other cats only see consequences on their next tick, by reading their
`social:inbox`. That keeps per-cat cadence authority unchanged.

## Phased rollout

1. Mirror snapshots into `WorldState` (no behavior change).
2. Move object inventory (`EdibleStore`) into Python.
3. Add a deterministic `SocialRoom` that only logs co-location.
4. Add the LLM moderator + speaker (real dialogue).
5. Render dialogue in Unity (speech bubble / chirp cue only).
6. Demote `GoalEventBus` to advisory (`reason` flows through the same path,
   but backend declares the step outcome).

Each phase ships independently and the cat keeps working between phases.

## What this is not

- Not a redesign of cognition (slow / fast / reflect mind stays).
- Not a memory rewrite (raw + STM tables from ADR-009 stay).
- Not a removal of Unity's body code (NavMesh, motor, watchdogs all stay).
- Not real-time multi-cat sync. Two cats meeting "at the same instant"
  still resolves cat-by-cat, with the second cat reading a pending inbox.
