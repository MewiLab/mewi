# Mewi Backend — Architecture

## System Overview

```mermaid
graph TB
    subgraph Unity["Unity Game (Stray Cat)"]
        UB[AgentBridge.cs<br/>HTTP server :8080]
        CAT[Cat Character<br/>Malbers Controller]
        UB <-->|actions / state| CAT
    end

    subgraph Backend["FastAPI Backend (:8000)"]
        direction TB

        subgraph API["HTTP API Layer"]
            R1[POST /agent/tick]
            R2[GET /agent/status/:id]
            R3[GET /agent/context]
        end

        subgraph Core["Agent Core"]
            direction TB
            AGENT[CreatureAgent<br/>eye + memory + body]
            GRAPH[LangGraph<br/>perceive→remember→reason→act→reflect]
        end

        subgraph Workers["Background Workers"]
            AW[AgentWorker<br/>autonomous tick loop]
            MW[MicrologWorker<br/>embedding batch]
        end

        subgraph Infra["Infrastructure"]
            REDIS[(Redis<br/>status cache + tick cache)]
            SB[(Supabase<br/>tick history + micrologs)]
        end
    end

    subgraph LLM["LLM Backend"]
        OAI[OpenAI / Anthropic<br/>/ Ollama / OpenRouter]
    end

    Unity <-->|GET /state, POST /action| Backend
    R1 --> GRAPH
    AW --> GRAPH
    GRAPH --> AGENT
    AGENT <-->|GET /state, POST /action| UB
    GRAPH -->|reason node| OAI
    AGENT --> REDIS
    AGENT --> SB
    MW --> SB
```

## Agent Tick Flow

Each tick (triggered by Unity POST or the autonomous worker) runs a 5-node LangGraph:

```mermaid
sequenceDiagram
    participant U as Unity / Worker
    participant G as LangGraph
    participant Eye as SnapshotManager (eye)
    participant Mem as MemoryManager (memory)
    participant LLM as LLM Provider
    participant Body as ActionManager (body)
    participant UB as AgentBridge (Unity)

    U->>G: ainvoke({ raw_payload })

    G->>Eye: perceive(raw_payload)
    Eye-->>G: PerceptionSummary | PerceptionError

    alt perception OK
        G->>Mem: recall(last_n=5)
        Mem-->>G: MemoryRecall

        G->>LLM: ainvoke([system, user])
        LLM-->>G: { action, kwargs, reasoning }

        alt action != "wait"
            G->>Body: execute(action, **kwargs)
            Body->>UB: POST /action
            UB-->>Body: { ok: true }
            Body-->>G: ActionResult
        end
    else perception error
        G->>G: chosen_action = wait (no LLM call)
    end

    G->>G: reflect (log outcome)
    G-->>U: final state dict
```

## Module Dependency Map

```mermaid
graph LR
    subgraph Routes
        AR[agent_router]
        MR[micrologs_router]
        ASR[assets_router]
    end

    subgraph Services
        AS[AgentService]
        MS[memory_service]
        MLS[microlog_service]
    end

    subgraph Agent
        CA[CreatureAgent]
        GR[graph.py<br/>build_creature_graph]
        LLMP[LLMProvider]
        EYE[SnapshotManager]
        MEMM[MemoryManager]
        ACT[ActionManager]
        UC[HttpUnityClient]
    end

    subgraph Repositories
        REPO[MemoryRepository<br/>Supabase]
        CACHE[MemoryCache<br/>Redis]
    end

    subgraph Workers
        AW[AgentWorker]
        MW[MicrologWorker]
    end

    AR --> AS
    AS --> GR
    AS --> MS
    MS --> REPO
    MS --> CACHE

    GR --> CA
    GR --> LLMP
    CA --> EYE
    CA --> MEMM
    CA --> ACT
    ACT --> UC

    AW --> AS
    MW --> MLS
    MLS --> REPO
```

## Startup Sequence

```mermaid
sequenceDiagram
    participant L as lifespan.py
    participant SB as Supabase
    participant R as Redis
    participant CA as CreatureAgent
    participant UB as Unity AgentBridge
    participant MS as memory_service

    L->>SB: create_supabase(settings)
    L->>R: create_redis(settings)
    L->>CA: create_creature_agent(unity_url)
    CA->>UB: GET /ping → connect
    CA->>UB: GET /actions → load action registry
    L->>L: build_creature_graph(agent, llm).compile()
    L->>MS: hydrate_agent(agent, supabase, redis)
    MS->>R: load_ticks (hot path)
    alt cache miss
        MS->>SB: load_recent_ticks (cold path)
        MS->>R: back-fill Redis
    end
    MS->>CA: memory.record(summary) × N
    L->>L: start AgentWorker + MicrologWorker tasks
    note over L: App ready to serve
```

## Data Flow: Perception Payload (Unity → Agent)

```mermaid
graph LR
    subgraph Unity JSON
        EP[environment_snapshot<br/>time_of_day, weather, entities]
        CP[creature_snapshot<br/>position, rotation_y, active_state, speed, sprint]
    end

    subgraph SnapshotManager
        V[_validate → Pydantic models]
        F[_filter_by_relevance<br/>drop entities > relevance_radius]
        T[_assess_threat<br/>SAFE / CAUTION / DANGER]
    end

    EP --> V
    CP --> V
    V --> F
    F --> T
    T --> PS[PerceptionSummary]
    PS --> MEM[MemoryManager.record]
    PS --> CTX[to_prompt_context → LLM]
```

## LLM Provider Configuration

```mermaid
graph TD
    ENV[.env: LLM_PROVIDER] --> LP[create_llm_provider]
    LP -->|openai| OAI[ChatOpenAI]
    LP -->|anthropic| ANT[ChatAnthropic]
    LP -->|ollama| OLL[ChatOpenAI<br/>base_url=localhost:11434]
    LP -->|openrouter| OR[ChatOpenAI<br/>base_url=openrouter.ai/api/v1]
    OAI & ANT & OLL & OR --> PROT[LLMProvider Protocol<br/>invoke / ainvoke]
    PROT --> GR[graph reason node]
```

## Key Design Decisions

| Decision | Why |
|---|---|
| `CreatureAgent` is the **body**, LangGraph is the **brain** | Swap graphs (reactive, planning, hardcoded) without touching the creature |
| Node factories close over `agent` — graph state is pure data | State is serializable; LangGraph can checkpoint it |
| `LLMProvider` is a Protocol, not a base class | Any LangChain `ChatModel` satisfies it; no inheritance coupling |
| `UnityClientProtocol` injected into `ActionManager` | Swap `HttpUnityClient` ↔ `MockUnityClient` without touching logic |
| `AgentService` owns status transitions (`thinking` / `idle`) | Router stays thin; status always resets even on graph failure |
| `persist_tick` runs as FastAPI `BackgroundTask` | Supabase write never blocks the Unity response |
| Integration tests guarded by `CONFIRM_PAID=1` | Prevent accidental real LLM / DB calls in CI |
