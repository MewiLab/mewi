# ADR-007: Unity Periodic Tick 

**Status:** Accepted <br>
**Date:** 2026-05-04 <br>
**Deciders:** vanillasky <br>
**Relates to:** ADR-005 (Unity client architecture), ADR-003 (FastAPI backend)

```mermaid
sequenceDiagram
    participant PM as PeriodicMind
    participant AMB as AgentMindBridge
    participant SM as SnapshotManager
    participant LLM as LLM Backend
    participant UMT as Unity Main Thread

    %% Step 1
    PM->>AMB: SendTick()
    AMB->>SM: BuildJson()
    SM-->>AMB: Returns JSON

    %% Step 2
    AMB->>LLM: POST /agent/tick (JSON)
    LLM-->>AMB: 202 Accepted (job_id)

    %% Step 3 (Polling)
    loop Poll until done
        AMB->>LLM: GET /agent/tick/result/{job_id}
        LLM-->>AMB: status: pending
    end

    AMB->>LLM: GET /agent/tick/result/{job_id}
    LLM-->>AMB: status: done, action: move

    %% Step 4
    AMB->>AMB: ParseAndStore()\n(Convert JSON to LLMIntent)

    %% Step 5
    UMT->>AMB: Tick()
    AMB->>AMB: ResolvePendingTarget()\n(Link to 3D Transforms)

    %% Step 6
    PM->>AMB: TryConsume()
    AMB-->>PM: Returns Intent
```

## Component Lifecycle & Tick Sequence

```mermaid
sequenceDiagram
    participant Unity as Unity Engine
    participant CC as CreatureController
    participant PM as PeriodicMind
    participant AMB as AgentMindBridge
    participant Others as Perception / Reflex / Brain / Motor

    %% ── Awake ────────────────────────────────────────────────────────────────
    Unity->>CC: Awake()
    CC->>Others: GetComponent + Init()
    CC->>PM: GetComponent + Init(board, config)
    CC->>AMB: GetComponent + Init(snapshot)
    Note over CC: All dependencies injected.<br/>No ticking yet.

    %% ── Start ────────────────────────────────────────────────────────────────
    Unity->>CC: Start()
    CC->>PM: StartThinking()
    Note over PM: Launches ThinkLoop coroutine.<br/>Fires every mindTickInterval seconds<br/>(independent of Update).

    %% ── Update loop (every frame) ────────────────────────────────────────────
    loop Every Frame
        Unity->>CC: Update()
        CC->>CC: board.ClearFrameFlags() + ScoreDrives()
        CC->>AMB: Tick()  [ResolvePendingTarget]
        CC->>Others: Perception.Tick()
        CC->>Others: ZoneScanner.Tick()
        CC->>Others: Reflex.Tick()
        CC->>Others: Brain.Tick()
        CC->>Others: Motor.Tick()
        CC->>CC: board.UpdateDebugDisplay()
    end

    %% ── PeriodicMind fires on its own timer ──────────────────────────────────
    Note over PM: Timer fires (mindTickInterval)
    PM->>PM: UpdateMood()
    PM->>PM: ResolveIntent()
    PM->>AMB: SendTick(board)  [LLM mode]
    PM->>AMB: TryConsumeResponse()  [LLM mode]
    PM->>CC: board.SetMindIntent()  [sole writer]

    %% ── OnDisable ────────────────────────────────────────────────────────────
    Unity->>CC: OnDisable()
    CC->>PM: StopThinking()
    Note over PM: Coroutine cancelled.<br/>No more ticks.
```