# Current Unity/Backend Workflow

This document describes the runtime flow after the movement reliability and
action queue changes. It is meant to be the fast map for debugging "why did the
cat not do the next thing yet?"

## Backend Tick Loop

```mermaid
flowchart TD
    A[PeriodicMind timer fires] --> B{Backend request in flight?}
    B -- yes --> B1[Wait; send no snapshot]
    B -- no --> C{Local plan or body busy?}
    C -- yes --> C1[Wait; send no snapshot]
    C -- no --> D[Build SnapshotPayload]
    D --> E[Send websocket tick with previous plan report]
    E --> F[Reflect updates place memory]
    F --> G[Slow Mind chooses intent]
    G --> H[Fast Mind builds ordered action plan]
    H --> I[Backend returns plan]
    I --> J[AgentNetworkManager stores latest plan]
    J --> K[PeriodicMind consumes plan on next tick]
```

Important invariant: Unity sends a new snapshot only when the previous backend
request is done and the local body is no longer executing a queued command.

Backend thinking is split intentionally: `reflect` writes memory from the
completed queue, `slow_mind` chooses a durable intent, and `fast_mind` converts
that intent into concrete Unity actions.

## Local Plan Queue

```mermaid
flowchart TD
    A[Backend plan] --> B[PeriodicMind normalizes steps]
    B --> C[CreatureBlackboard.ReplaceMindPlan]
    C --> D[CreatureWorker peeks head intent]
    D --> E[CreatureWorker builds MotorCommand]
    E --> F[MalbersAnimalAdapter.Apply]
    F --> G{Adapter IsBusy?}
    G -- yes --> H[Worker keeps active intent]
    H --> G
    G -- no --> I[Worker records step completion]
    I --> J{More queued intents?}
    J -- yes --> D
    J -- no --> K[PlanExecutionReport queued]
```

The blackboard queue can be empty while the worker still owns an active intent.
That is expected for long animations: the intent has already been popped from
the queue, but the adapter is still busy with the body.

## Navigation Recovery

```mermaid
flowchart TD
    A[go_to/follow/wander/flee] --> B[Project destination to NavMesh]
    B -- found --> C[Use Malbers SetDestination or manual fallback]
    B -- not found --> D[Raw warp reliability fallback]
    C --> E[NavigationWatchdog samples distance to target]
    E --> F{Closer to destination?}
    F -- yes --> E
    F -- no for timeout --> G[Repath]
    G --> H{Repaths exhausted or hard timeout?}
    H -- no --> E
    H -- yes --> I[Warp to NavMesh-projected point or raw destination]
    D --> J[Mark command complete]
    I --> J
```

Target positions now use the perceived entity position from the snapshot when
available. This avoids moving to a prefab root/pivot when the meaningful point
is a `SmartObject.perceptionCenter`.

## Action Execution

```mermaid
flowchart TD
    A[eat/sit/lie/sleep/etc.] --> B[Execute Malbers Action mode]
    B --> C[ActionWatchdog waits for mode start]
    C --> D{Mode started?}
    D -- yes --> E[Let animation run]
    D -- no before timeout --> H[Force cleanup]
    E --> F{OnModeEnd fired?}
    F -- yes --> G[Start post-action cooldown]
    F -- no before max duration --> H
    H --> G
    G --> I{Cooldown done?}
    I -- no --> G
    I -- yes --> J[Adapter IsBusy false; worker advances]
```

Action timeout and cooldown are configurable through
`ActionExecutionConfig`. The goal is to let real animations finish, but never
let a looping/resting Malbers state block the next LLM command forever.
