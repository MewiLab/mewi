# ADR-011: Unity LLM Creature Architecture Diagrams

**Status:** Proposed
**Date:** 2026-05-05
**Deciders:** vanillasky
**Relates to:** ADR-005 (Unity creature AI), ADR-007 (Periodic Tick), ADR-008 (Bridge sync), ADR-009 (LLM Intent / Multi-Agent), ADR-010 (Hardening)

## Context

ADR-009 and ADR-010 define the current LLM-only creature path:

- Unity sends periodic snapshots to the backend.
- The backend returns one semantic command.
- Unity resolves scene targets, writes a Mind intent, executes it through `CreatureMotor`, and reports lifecycle events.
- Reflex/Tactical inhibition is explicitly future work.

The system now has enough moving pieces that one large diagram is hard to read. This ADR records the same architecture as several smaller Mermaid diagrams, each from one viewpoint.

## Diagram 1: System Context

```mermaid
flowchart LR
    User["Designer / Playtester"]
    Unity["Unity Runtime"]
    Backend["FastAPI + LangGraph Backend"]
    LLM["LLM / Tool Planner"]
    Scene["Scene Semantics\nSmartObject, ZoneVolume,\nNamedTargetRegistry"]
    Malbers["Malbers Animal Controller\nMAnimal + MAnimalAIControl"]

    User --> Unity
    Unity -->|"snapshot JSON\nPOST /api/v1/agent/tick"| Backend
    Backend --> LLM
    LLM --> Backend
    Backend -->|"job result\nGET /api/v1/agent/tick/result/{job_id}"| Unity
    Unity -->|resolve target keys| Scene
    Unity -->|execute command| Malbers
    Unity -->|ActionReport\nPOST /api/v1/agent/report| Backend
```

## Diagram 2: Per-Cat Unity Components

```mermaid
flowchart TB
    subgraph Cat["One Cat GameObject"]
        CC["CreatureController"]
        Board["CreatureBlackboard\ncreatureId, intent slots,\nperception, mood, health"]
        PM["PeriodicMind\nLLM timer + command acceptance"]
        Bridge["AgentMindBridge\npure async transport"]
        Snapshot["SnapshotManager\nchannel registry"]
        Reporter["HttpActionReporter\ncommand lifecycle egress"]
        Motor["CreatureMotor\nonly production Malbers caller"]
        Perception["CreaturePerception"]
        ZoneScanner["ZoneScanner"]
        ZoneTracker["SmartZoneTracker"]
        Reflex["CreatureReflexRunner\nfuture in LLM mode"]
        Brain["CreatureBrain\nfuture in LLM mode"]
    end

    subgraph Scene["Scene-Level Semantics"]
        TargetRegistry["NamedTargetRegistry"]
        SmartObjects["SmartObject markup"]
        Zones["ZoneVolume markup"]
    end

    subgraph Malbers["Malbers Components"]
        Animal["MAnimal"]
        AI["MAnimalAIControl"]
        Nav["NavMeshAgent"]
    end

    CC --> Board
    CC --> PM
    CC --> Perception
    CC --> ZoneScanner
    CC --> ZoneTracker
    CC --> Motor
    CC -.->|LLM mode skips| Reflex
    CC -.->|LLM mode skips| Brain

    PM --> Bridge
    PM --> Snapshot
    PM --> Reporter
    PM --> TargetRegistry
    Snapshot --> Board
    Perception --> Board
    ZoneScanner --> Board
    ZoneTracker --> Board
    TargetRegistry --> SmartObjects
    TargetRegistry --> Zones
    Motor --> Board
    Motor --> Reporter
    Motor --> Animal
    Motor --> AI
    AI --> Nav
```

## Diagram 3: Unity Frame Loop

```mermaid
sequenceDiagram
    participant Unity
    participant CC as CreatureController
    participant Board as CreatureBlackboard
    participant Perception
    participant Zones as ZoneScanner/SmartZoneTracker
    participant Reflex as ReflexRunner
    participant Brain as CreatureBrain
    participant Motor as CreatureMotor

    loop Every frame
        Unity->>CC: Update()
        CC->>Board: ClearFrameFlags()
        CC->>Board: ScoreDrives()
        CC->>Perception: Tick()
        CC->>Zones: Tick()
        alt MindMode.LLM
            CC-->>Reflex: skipped for current LLM-only phase
            CC-->>Brain: skipped for current LLM-only phase
        else Simulated / future layered mode
            CC->>Reflex: Tick()
            CC->>Brain: Tick()
        end
        CC->>Motor: Tick()
        Motor->>Board: ResolveActiveIntent()
        Motor->>Motor: Execute via Malbers/NavMesh
        CC->>Board: UpdateDebugDisplay()
    end
```

## Diagram 4: Periodic LLM Tick

```mermaid
sequenceDiagram
    participant PM as PeriodicMind
    participant Bridge as AgentMindBridge
    participant Snapshot as SnapshotManager
    participant Backend
    participant Reporter as HttpActionReporter

    loop Every mindTickInterval
        PM->>Bridge: TryConsume()
        alt LLMIntent available
            Bridge-->>PM: LLMIntent
            PM->>PM: ApplyLLMResponse()
        else No response yet
            Bridge-->>PM: none
        end

        PM->>Snapshot: BuildJson(requestId)
        Snapshot-->>PM: snapshot JSON
        PM->>Bridge: SendTick(json)
        Bridge->>Backend: POST /api/v1/agent/tick
        Backend-->>Bridge: 202 {job_id}

        loop Poll until done / error / timeout
            Bridge->>Backend: GET /api/v1/agent/tick/result/{job_id}
            Backend-->>Bridge: pending / done / error
        end

        alt New bridge failures observed
            PM->>PM: Debug warning with FailedTickCount delta
        end
    end
```

## Diagram 5: Snapshot Build

```mermaid
flowchart LR
    PM["PeriodicMind\nrequestId"]
    SM["SnapshotManager"]
    Payload["SnapshotPayload\nagent_id, requestId,\ncommandId, time"]
    Self["SelfChannel"]
    Mood["MoodChannel"]
    Health["HealthChannel"]
    Entities["EntitiesChannel"]
    Spatial["SpatialChannel"]
    Board["CreatureBlackboard"]
    Json["JSON string"]

    PM --> SM
    SM --> Payload
    SM --> Self
    SM --> Mood
    SM --> Health
    SM --> Entities
    SM --> Spatial
    Self --> Board
    Mood --> Board
    Health --> Board
    Entities --> Board
    Spatial --> Board
    Payload --> Json
    Self --> Json
    Mood --> Json
    Health --> Json
    Entities --> Json
    Spatial --> Json
```

## Diagram 6: Command Acceptance in `PeriodicMind`

```mermaid
flowchart TD
    A["Consume LLMIntent"] --> B{"intent empty or wait?"}
    B -->|yes| Drop["Drop silently"]
    B -->|no| Normalize["Normalize action\nstop -> stop_moving\nmove -> go_to in bridge"]
    Normalize --> C{"targetKey present?"}
    C -->|yes| Resolve["NamedTargetRegistry.TryResolve"]
    C -->|no| Validate["Validate command shape"]
    Resolve --> D{"target found?"}
    D -->|no| RejectTarget["Report rejected\nunknown target"]
    D -->|yes| Validate
    Validate --> E{"follow without target?"}
    E -->|yes| RejectFollow["Report rejected\nfollow requires target"]
    E -->|no| F{"go_to without target\nand zero destination?"}
    F -->|yes| RejectGoTo["Report rejected\ngo_to needs target or destination"]
    F -->|no| G{"Duplicate active Mind intent?"}
    G -->|yes| DropDuplicate["Drop silently\nno new commandId"]
    G -->|no| H{"Previous Mind command?"}
    H -->|yes| Cancel["Report cancelled"]
    H -->|no| NewId["Generate commandId"]
    Cancel --> NewId
    NewId --> ClearTactical["ClearTacticalIntent\nLLM-only phase"]
    ClearTactical --> FollowTarget["followTarget = target only for follow\notherwise null"]
    FollowTarget --> SetMind["SetMindIntent(action, destination,\ncommandId, requestId, targetKey)"]
    SetMind --> Accepted["Report accepted"]
```

## Diagram 7: Motor Execution

```mermaid
flowchart TD
    Tick["CreatureMotor.Tick"] --> Resolve["board.ResolveActiveIntent()"]
    Resolve --> Changed{"intent or commandId changed?"}
    Changed -->|no| Execute["ExecuteIntent per frame"]
    Changed -->|yes| Exit["Exit old intent"]
    Exit --> Enter["Enter new intent"]

    Enter --> Type{"Intent type"}
    Type -->|go_to| GoTo["MAnimalAIControl.SetDestination"]
    Type -->|follow| Follow{"followTarget exists?"}
    Follow -->|yes| SetTarget["MAnimalAIControl.SetTarget(target, true)"]
    Follow -->|no| Failed["Report failed\nclear Mind"]
    Type -->|stop_moving| Stop["MAnimalAIControl.Stop\nreport succeeded"]
    Type -->|wander| Wander["Pick NavMesh wander target"]
    Type -->|action intent| TryMode["MAnimal.Mode_TryActivate(actionMode.ID, abilityIndex)"]
    Type -->|die| Death["State_Force(deathState)"]
    Type -->|unknown| Failed

    GoTo --> Started["Report started"]
    SetTarget --> Started
    Stop --> Started
    Wander --> Started
    Death --> Started
    TryMode --> ModeOk{"Malbers accepted?"}
    ModeOk -->|yes| Started
    ModeOk -->|no| Failed

    Execute --> Arrived{"go_to arrived?"}
    Arrived -->|yes| Success["Report succeeded\nClearMindIntent"]
    Arrived -->|no| FollowLost{"follow target disappeared?"}
    FollowLost -->|yes| Failed
    FollowLost -->|no| Continue["Continue"]
```

## Diagram 8: Action Report Flow

```mermaid
sequenceDiagram
    participant PM as PeriodicMind
    participant Motor as CreatureMotor
    participant Reporter as HttpActionReporter
    participant Backend

    PM->>Reporter: accepted / rejected / cancelled
    Reporter->>Backend: POST /api/v1/agent/report

    Motor->>Reporter: started
    Reporter->>Backend: POST /api/v1/agent/report

    alt navigation arrived
        Motor->>Reporter: succeeded
        Reporter->>Backend: POST /api/v1/agent/report
    else Mode_TryActivate refused
        Motor->>Reporter: failed
        Reporter->>Backend: POST /api/v1/agent/report
    else action mode ended
        Motor->>Reporter: succeeded
        Reporter->>Backend: POST /api/v1/agent/report
    end
```

## Diagram 9: Multi-Agent Scaling

```mermaid
flowchart TB
    subgraph UnityScene["Unity Scene"]
        CatA["Cat A\nagent_id=cat_a"]
        CatB["Cat B\nagent_id=cat_b"]
        CatN["Cat N\nagent_id=cat_n"]
        Registry["Shared NamedTargetRegistry"]
    end

    subgraph CatAComponents["Per Cat Components"]
        PMA["PeriodicMind"]
        BridgeA["AgentMindBridge"]
        SnapshotA["SnapshotManager"]
        ReporterA["HttpActionReporter"]
        MotorA["CreatureMotor"]
    end

    Backend["Backend\nroutes by agent_id"]
    AgentStateA["LangGraph state: cat_a"]
    AgentStateB["LangGraph state: cat_b"]
    AgentStateN["LangGraph state: cat_n"]

    CatA --> PMA
    PMA --> BridgeA
    PMA --> SnapshotA
    PMA --> ReporterA
    PMA --> MotorA
    CatA --> Registry
    CatB --> Registry
    CatN --> Registry
    BridgeA -->|snapshot agent_id=cat_a| Backend
    ReporterA -->|report agent_id=cat_a| Backend
    Backend --> AgentStateA
    Backend --> AgentStateB
    Backend --> AgentStateN
```

## Diagram 10: Legacy Test Harness Guard

```mermaid
flowchart TD
    Add["AgentBridge component starts\nTest-only legacy harness"] --> Check{"AgentMindBridge in same hierarchy?"}
    Check -->|yes| Disable["Log error\nDisable AgentBridge"]
    Check -->|no| Listener["Start local HttpListener\n/test harness only"]
    Listener --> Direct["Direct Malbers calls\noutside production LLM path"]

    Production["Production NPC prefab"] --> Uses["Uses AgentMindBridge"]
    Production --> NotUses["Must not use AgentBridge"]
```

## Decision

Use this ADR as the canonical visual map of the Unity LLM creature architecture. Implementation decisions still live in the related ADRs:

- ADR-007 for tick cadence.
- ADR-008 for async bridge synchronization.
- ADR-009 for LLM intent identity, target resolution, reports, and Malbers command semantics.
- ADR-010 for multi-agent cleanup and guardrails.

## Consequences

**Positive**

- New contributors can understand the architecture without reading every script first.
- Diagrams stay small enough to perceive one concern at a time.
- Future Reflex/Tactical inhibition work has a clear place to add new diagrams without rewriting the LLM-only ones.

**Negative**

- Diagrams can drift from code. Any change to tick order, command lifecycle, reports, or component ownership should update this ADR in the same PR.
