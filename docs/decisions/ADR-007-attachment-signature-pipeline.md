# ADR-007: Attachment Signature Pipeline

- **Status:** Accepted
- **Date:** 2026-05-22
- **Scope:** `backend/app/models/attachment.py`, `backend/app/services/attachment_preprocess.py`, `backend/app/services/attachment_map.py`, `backend/app/repositories/attachment_repo.py`, `backend/app/api/routes/attachment_router.py`, `frontend/app/Assets/Scripts/AgentIntegration/Attachment/*`, `frontend/app/Assets/Scripts/AgentIntegration/Bridge/ApiRoutes.cs`

## Context

Each cat agent can be assigned a hidden attachment profile through its system
prompt. That assigned cat profile is the controlled stimulus condition, not a
measurement of the cat.

The research hypothesis is about the player: the player's interaction pattern
with a controlled ambiguous other may reveal a relational schema. The design
draws from:

- Ainsworth's Strange Situation logic: standardized episodes create comparable
  separation, reunion, approach, and withdrawal moments.
- Projective logic: responses to a controlled ambiguous other can reflect the
  participant's own expectations about closeness, distance, and repair.

The pipeline must therefore preserve the independent variable
(`cat_assigned_type`) and infer only the dependent variable
(`player_attachment_estimate`). It must also stay honest: this prototype
produces a low-confidence rule-based estimate until validated against a
self-report instrument such as ECR-R.

## Decision

Implement the attachment pipeline as three explicit contracts and three
deterministic stages:

1. `RawAttachmentEvent`: Unity facts, no interpretation.
2. `AttachmentSessionFeatures`: theory-grounded behavioral constructs.
3. `AttachmentAnalysisResult`: transparent ATF rule output.

Persist all three layers to Supabase so the research trail is auditable and the
ATF rules can be rerun later without recollecting Unity logs.

## Dataflow

```mermaid
flowchart TD
    A[Unity session logs] --> B[POST /api/v1/attachment/session]
    B --> C[(attachment_raw_events)]
    B --> D[attachment_preprocess.py]
    D --> E[AttachmentSessionFeatures]
    E --> F[(attachment_session_features)]
    E --> G[attachment_map.py / ATF rules]
    G --> H[AttachmentAnalysisResult]
    H --> I[(attachment_results)]
    H --> J[Unity reveal / research UI]

    K[Hidden cat system prompt] -. assigned condition .-> A
    K -. cat_assigned_type .-> E
    K -. cat_assigned_type .-> H
```

## Schema Contract

Raw event:

```json
{
  "session_id": "uuid",
  "cat_id": "milo",
  "event": "cat_withdrew",
  "t": 1234.5,
  "distance": 2.3,
  "meta": {}
}
```

Feature row:

```json
{
  "session_id": "uuid",
  "cat_id": "milo",
  "cat_assigned_type": "avoidant",
  "reapproach_latency_mean": 4.2,
  "pursuit_ratio": 0.7,
  "time_near_ratio": 0.45,
  "reunion_response": 0.8,
  "withdrawal_tolerance": 12.1,
  "n_events": 47
}
```

ATF output:

```json
{
  "session_id": "uuid",
  "cat_id": "milo",
  "cat_assigned_type": "avoidant",
  "player_attachment_estimate": "anxious",
  "scores": {
    "secure": 0.2,
    "anxious": 0.6,
    "avoidant": 0.15,
    "disorganized": 0.05
  },
  "confidence": "low"
}
```

## Feature Ownership

`attachment_preprocess.py` is pure code. It converts event timing and distance
facts into attachment-flavored response features.

```mermaid
flowchart LR
    A[cat_withdrew] --> B[player_approached after withdrawal]
    B --> C[reapproach_latency_mean]
    A --> D[player_approached vs player_retreated]
    D --> E[pursuit_ratio]
    F[distance samples] --> G[time_near_ratio]
    H[player_returned_after_absence] --> I[approach / closeness after return]
    I --> J[reunion_response]
    A --> K[time until retreat or distance]
    K --> L[withdrawal_tolerance]
```

Features should measure the player's response to cat-initiated or episode
events, not generic activity.

## ATF Rules

`attachment_map.py` is transparent rules, not LLM or ML.

```mermaid
flowchart TD
    A[AttachmentSessionFeatures] --> B{Enough evidence?}
    B -- no --> C[undetermined + low confidence]
    B -- yes --> D[Score prototypes]
    D --> E[Anxious: pursuit + intense reunion + low tolerance]
    D --> F[Avoidant: low pursuit + muted reunion + distance]
    D --> G[Secure: moderate pursuit + reunion + tolerance]
    D --> H[Disorganized: conflicting pursuit/reunion/tolerance]
    E --> I[Normalize scores]
    F --> I
    G --> I
    H --> I
    I --> J[Return top estimate + low confidence]
```

The low confidence is intentional. The estimate is a prototype research signal,
not a diagnosis.

## Endpoint Behavior

`POST /api/v1/attachment/session` runs inline for now:

```mermaid
sequenceDiagram
    participant U as Unity
    participant API as FastAPI
    participant Repo as AttachmentRepository
    participant Pre as Preprocess
    participant ATF as Attachment Map
    participant DB as Supabase

    U->>API: session_id + cat_assigned_type + events
    API->>Repo: store raw events
    Repo->>DB: insert attachment_raw_events
    API->>Pre: preprocess(events)
    Pre-->>API: feature row
    API->>Repo: store features
    Repo->>DB: upsert attachment_session_features
    API->>ATF: atf(features)
    ATF-->>API: result
    API->>Repo: store result
    Repo->>DB: upsert attachment_results
    API-->>U: result
```

Inline processing is acceptable because the current prototype dataset is small
and externally triggered. Move this to a worker only if analysis becomes slow or
batch-based.

## Unity Client

Unity owns only fact logging and delivery. It should not infer attachment
meaning locally.

```mermaid
flowchart TD
    A[CreatureBlackboard perception] --> B[AttachmentBehaviorLogger]
    C[Manual interaction scripts] --> B
    D[Mind intent changes] --> B
    B --> E[AttachmentSessionPayload]
    E --> F[AttachmentSessionSender]
    F --> G[POST /api/v1/attachment/session]
    G --> H[AttachmentAnalysisResponse]
    H --> I[Reveal UI / research debug]

    J[Inspector catAssignedType] --> B
    J -. controlled stimulus .-> E
```

Unity files:

- `AttachmentPayloads.cs`: serializable request/response DTOs and string
  constants shared by logger and sender.
- `AttachmentBehaviorLogger.cs`: session id ownership, automatic distance and
  cat-intent event logging, plus manual hooks for explicit player interactions.
- `AttachmentSessionSender.cs`: thin HTTP transport using `BackendConfig`,
  `ApiRoutes`, API-key headers, timeout behavior, and the backend response DTO.

The logger records backend event names only. Higher-level constructs such as
`pursuit_ratio` and `reunion_response` remain backend-owned so the experiment
keeps one auditable interpretation layer.

## Supabase Tables

```mermaid
erDiagram
    attachment_raw_events }o--|| attachment_session_features : aggregates
    attachment_session_features ||--|| attachment_results : classifies

    attachment_raw_events {
        uuid id
        uuid session_id
        text cat_id
        text cat_assigned_type
        text event
        float t
        float distance
        jsonb meta
        timestamptz created_at
    }

    attachment_session_features {
        uuid id
        uuid session_id
        text cat_id
        text cat_assigned_type
        float reapproach_latency_mean
        float pursuit_ratio
        float time_near_ratio
        float reunion_response
        float withdrawal_tolerance
        int n_events
        timestamptz created_at
    }

    attachment_results {
        uuid id
        uuid session_id
        text cat_id
        text cat_assigned_type
        text player_attachment_estimate
        jsonb scores
        text confidence
        int n_events
        timestamptz created_at
    }
```

## Consequences

Benefits:

- The independent variable is explicit and carried end to end.
- Raw logs, features, and output are all auditable.
- ATF rules are inspectable by a professor and can be mapped to constructs.
- The system can refuse to over-claim when evidence is thin.

Tradeoffs:

- Rule thresholds are provisional and must be validated.
- Sparse Unity events approximate time-based features from event samples.
- The endpoint is synchronous for the prototype and may need a worker later.

## Acceptance Checks

- A session payload stores raw events before analysis.
- Preprocessing returns the same features for the same event list.
- Low event count returns `undetermined` and `confidence: low`.
- `cat_assigned_type` appears in raw rows, features, and results.
- The endpoint returns an auditable result with scores and feature summary.
