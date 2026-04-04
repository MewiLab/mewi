# ADR-001: Project Technology Stack — Mobile 3D Agent App

**Status:** Accepted 
**Date:** 2026-03-08
**Deciders:** vanillasky



## Context

We are building a mobile-first 3D application featuring an AI-powered virtual cat companion. The product requires:

1. **Real-time 3D rendering** with first-person camera on iOS and Android.
2. **Device sensor integration** — gyroscope, accelerometer, GPS — to ground the experience in the player's physical world.
3. **An agentic AI backend** — an LLM-driven agent that maintains memory, personality, and evolving relationships with the user.
4. **Low operational overhead at MVP** — a small team must be able to ship, monitor, and iterate without managing Kubernetes clusters or multi-cloud Terraform configs.
5. **Cost predictability** — free tiers and serverless pricing for as long as possible; no surprise bills from idle infrastructure.

The stack must bridge two very different worlds: a C#/Unity client and a Python/LLM backend. The choices below optimise for developer velocity at MVP while keeping a credible path to scale.



## Decision

We adopt a three-layer architecture: **Client (Unity)**, **Runtime & Backend (FastAPI + Supabase)**, and **Deploy & Observability (Railway/Fly.io + Langfuse)**.

---

### Layer 1 — Client (Unity)

| Component | Choice | Rationale |
|---|---|---|
| **Client Engine** | Unity 6 / C# | Proven cross-platform 3D engine for mobile. First-person camera, physics, and asset pipeline are mature. Large ecosystem of plugins and community support. |
| **UI System** | Unity UI Toolkit | Modern retained-mode UI, well-suited for HUD overlays, popups, and menus. Replaces the older UGUI with better styling and layout primitives. |
| **Navigation** | Unity AI Navigation | Built-in NavMesh pathfinding is more than sufficient for NPC movement on the small indoor/outdoor maps this product requires. No need for a third-party solution. |
| **State Machine** | Custom C# FSM (ScriptableObject-based) | A lightweight, inspector-friendly FSM avoids the weight of a visual scripting plugin. ScriptableObject states are easy to author, test, and version-control. |
| **Device Sensors** | Unity Input System + Location Service | Gyroscope, accelerometer, and GPS are covered natively. Platform-specific plugins will only be added if a sensor gap appears during device testing. |

**Key trade-off:** Unity's C# runtime means the client and backend do not share a language. This is acceptable because the boundary between them is a well-defined REST/WebSocket API, and each side benefits from its own ecosystem (C# for 3D; Python for ML/LLM).

---

### Layer 2 — Runtime & Backend

#### 2a. Managed Services (Supabase)

| Component | Choice | Rationale |
|---|---|---|
| **Auth** | Supabase Auth | Generous free tier, email/OAuth/magic-link out of the box. Eliminates the need to stand up Cognito or Auth0 and the associated AWS overhead. |
| **DB — Client Profiles** | Supabase (PostgreSQL) | Relational data fits user profiles, cat trait tables, and bond progression naturally. Row-level security policies enforce multi-tenant isolation without application code. |
| **DB — Realtime Data** | Supabase Realtime | WebSocket layer built on Postgres CDC (Change Data Capture). Enables live UI updates (e.g., cat mood shifts) without polling and without requiring a separate GraphQL schema. |
| **DB — Agent Vector Store** | Supabase pgvector extension | Vector similarity search for agent memory lives in the same Postgres instance. One fewer service to provision, connect, and pay for compared to a standalone Pinecone or Weaviate. |
| **File Storage** | Supabase Storage | S3-compatible object store for user photos and voice memo blobs. Integrated auth policies reuse the same Supabase JWT, so no separate IAM configuration is needed. |

**Design principle:** Consolidating auth, relational data, vectors, realtime, and file storage into a single Supabase project minimises the number of services, secrets, and network hops at MVP. If any component hits a scaling ceiling post-launch, it can be extracted to a dedicated service without changing the data model.

#### 2b. Application Services (FastAPI + LangGraph)

| Component | Choice | Rationale |
|---|---|---|
| **Backend API** | FastAPI (Python) | The Python ecosystem is non-negotiable for the agent layer (LangChain, LangGraph, OpenAI SDK). FastAPI adds async support, automatic OpenAPI docs, and Pydantic validation with minimal boilerplate. |
| **Agent Framework** | LangGraph | Provides a graph-based orchestration model for multi-step agent workflows (observe → think → act → remember). More stable and easier to reason about than raw LangChain chains. |
| **Agent Memory** | Supabase Postgres + Upstash Redis | Long-term episodic memory (conversations, bond events) is persisted in Postgres. Short-term working memory and rate-limit counters use Upstash Redis, a serverless Redis with a generous free tier and per-request pricing. |
| **Domain Services** | FastAPI service modules (monorepo) | Snack, Aura, Semantic, and other domain services are organised as clearly bounded Python modules inside a single FastAPI app. This avoids premature micro-service overhead while keeping the codebase navigable. Extraction into separate services is straightforward if a module needs independent scaling. |

---

### Layer 3 — Deployment & Observability

| Component | Choice | Rationale |
|---|---|---|
| **Hosting** | Railway or Fly.io (FastAPI) + Supabase Cloud (DB/Auth/Storage) | One-command deploys from a Git repo. No Kubernetes manifests, no Terraform state files. Both Railway and Fly.io support auto-scaling, health checks, and preview environments. The choice between them will be finalised during the first deploy sprint based on region availability and cold-start performance. |
| **Observability** | Langfuse (preferred) or LangSmith | Langfuse is open-source and self-hostable, providing cost-effective LLM call tracing, prompt versioning, and evaluation dashboards. If the self-hosting burden proves too high, LangSmith is a managed fallback with deeper LangChain integration. |



## File / Module Structure (Backend)

```
backend/
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── api/
│   │   ├── routes_user.py       # Profile, auth callback endpoints
│   │   ├── routes_cat.py        # Cat state, interactions
│   │   └── routes_agent.py      # Agent conversation / action endpoints
│   ├── agent/
│   │   ├── graph.py             # LangGraph workflow definition
│   │   ├── memory.py            # Episodic + working memory adapters
│   │   └── tools/               # Agent tool implementations
│   ├── domain/
│   │   ├── snack.py             # Snack / feeding domain logic
│   │   ├── aura.py              # Aura / mood domain logic
│   │   └── semantic.py          # Semantic search & retrieval
│   ├── db/
│   │   ├── supabase_client.py   # Supabase connection + helpers
│   │   └── redis_client.py      # Upstash Redis connection
│   └── config.py                # Settings via pydantic-settings
├── tests/
├── evals/                       # → see ADR-002
└── pyproject.toml
```



## Consequences

**Positive:**

- A single Supabase project covers five infrastructure concerns (auth, relational DB, vectors, realtime, storage), dramatically reducing MVP ops burden.
- Python end-to-end on the backend means the agent, API, and domain logic share types, tests, and a single deploy artifact.
- Serverless-friendly choices (Upstash, Supabase, Railway/Fly.io) keep fixed costs near zero until real users arrive.
- The monorepo module structure supports fast iteration now and clean extraction later.

**Negative / Trade-offs:**

- **Supabase single-point-of-dependency.** If Supabase has an outage, auth, data, realtime, vectors, and storage all go down together. Mitigation: Supabase's Postgres is standard; migration to self-hosted or RDS is mechanical.
- **pgvector performance ceiling.** For very large vector corpora (millions of embeddings), pgvector may underperform dedicated vector databases. Acceptable at MVP scale; re-evaluate post-launch.
- **Language boundary.** C# on the client and Python on the backend mean no shared models or types. The OpenAPI spec generated by FastAPI serves as the contract; Unity codegen tools can consume it.
- **Langfuse self-hosting overhead.** Running Langfuse adds a container to manage. If the team lacks bandwidth, falling back to managed LangSmith trades cost for convenience.
- **Railway / Fly.io scaling limits.** Neither platform is designed for high-concurrency, compute-heavy workloads. If agent inference latency becomes a bottleneck, migration to ECS or Cloud Run will be necessary.



## Alternatives Considered

### A. Firebase instead of Supabase
**Rejected.** Firebase's NoSQL model (Firestore) is a poor fit for relational data like user profiles and cat trait progressions. Firebase Auth is comparable, but adopting Firestore would require denormalising data that is naturally relational, and there is no built-in vector search equivalent.

### B. Dedicated vector DB (Pinecone / Weaviate)
**Deferred.** Adding a separate vector service increases secrets, network hops, and cost. pgvector inside the existing Supabase Postgres instance is sufficient for the expected corpus size at MVP (tens of thousands of embeddings). Will revisit if retrieval latency or index size becomes a constraint.

### C. Node.js / TypeScript backend (shared language with potential web client)
**Rejected.** The agent layer depends heavily on the Python ML ecosystem (LangGraph, LangChain, OpenAI SDK, NumPy). A Node.js backend would require either rewriting these integrations or bridging to Python sub-processes, adding complexity with no clear benefit at this stage.

### D. AWS fully managed stack (Cognito, DynamoDB, Lambda, Bedrock)
**Rejected for MVP.** AWS provides superior scaling headroom but carries significant configuration overhead (IAM policies, VPC, CloudFormation/Terraform). The team's current size and velocity goals favour platforms with simpler deployment models. AWS components can be adopted incrementally (see ADR-002 for the eval pipeline, which already uses AWS for the data plane).

### E. Kubernetes (EKS / GKE) from day one
**Rejected.** Kubernetes is premature for a single FastAPI service with a small user base. The ops burden of cluster management, Helm charts, and ingress configuration would consume time better spent on product development.