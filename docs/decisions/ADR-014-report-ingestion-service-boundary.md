# ADR-014: Report Ingestion Service Boundary

- **Status:** Accepted
- **Date:** 2026-05-29 (implemented 2026-05-30)
- **Scope:** `mewi-backend/app/api/routes/report_router.py`, `mewi-backend/app/services/report/**`, `mewi-backend/app/api/deps.py`, `mewi-report/pipeline/scripts/process.py` (removed)
- **Builds on:** [ADR-012](ADR-012-mewi-report-raw-to-value-data-contract.md) (raw→value data contract), [ADR-013](ADR-013-mewi-report-auto-pipeline.md) (ingestion + processing pipeline)

## Context

ADR-013 established that Unity POSTs a raw session to `POST /api/v1/report/session`
and FastAPI is the only service that touches storage / future cloud infra.

The current implementation is correct in behavior but **the HTTP route does the
infra work itself**. `report_router.py` inlines:

- `_write_local_session(...)` — local disk write
- `_count_user_sessions(...)` — local disk scan
- `_raw_session_root(...)` — local path resolution

This couples the public contract (the route) to one specific storage backend
(local files). When storage becomes S3 and processing becomes a Lambda trigger,
that migration would mean editing the route handler — which is the thing we said
we wanted to avoid.

We also have nowhere clean to put the "is this user ready for processing?"
decision: `processing_queued` is currently hardcoded `False`.

## Decision

Introduce **one thin service** between the route and infra. The route only
validates the DTO and delegates; the service owns storage and the
processing-readiness decision. Storage is hidden behind a small **port**
(a `Protocol`) so the backend can swap local disk → S3 without touching the
route or the service logic.

Deliberately small. No repository pattern, no DI container, no event bus. Just:

```text
route (HTTP + auth + DTO validation)
  -> ReportIngestionService.ingest(payload)
       -> RawSessionStore.put(user_id, session_id, data)   # port
       -> RawSessionStore.count(user_id)                   # port
       -> ProcessingTrigger.maybe_queue(user_id, count)    # port (no-op today)
  <- ingest result -> response model
```

### Layout

```text
mewi-backend/app/services/report/
    __init__.py
    service.py        # ReportIngestionService (orchestration, no I/O details)
    store.py          # RawSessionStore Protocol + LocalFileRawSessionStore
    trigger.py        # ProcessingTrigger Protocol + NoopProcessingTrigger
```

### Ports (the only abstraction we add)

```python
# store.py
class RawSessionStore(Protocol):
    def put(self, user_id: str, session_id: str, data: dict) -> str: ...
    def count(self, user_id: str) -> int: ...


class LocalFileRawSessionStore:
    """Today: atomic write under mewi-report/pipeline/raw_data/sessions/.
    Moves verbatim out of report_router.py (_write_local_session, _count_user_sessions,
    _raw_session_root, _safe_segment)."""
    def __init__(self, root: Path) -> None: ...
    def put(self, user_id, session_id, data) -> str: ...   # returns storage_key
    def count(self, user_id) -> int: ...
```

```python
# trigger.py
class ProcessingTrigger(Protocol):
    def maybe_queue(self, user_id: str, session_count: int) -> bool: ...


class NoopProcessingTrigger:
    """Today: never queues. Developer runs process.py manually (ADR-013)."""
    def maybe_queue(self, user_id, session_count) -> bool:
        return False
```

### Service

```python
# service.py
class ReportIngestionService:
    def __init__(self, store: RawSessionStore, trigger: ProcessingTrigger,
                 ready_threshold: int = 5) -> None: ...

    def ingest(self, payload: ReportSessionPayload) -> IngestResult:
        storage_key = self.store.put(
            payload.user_id, payload.session.session_id,
            payload.model_dump(mode="json"),
        )
        count = self.store.count(payload.user_id)
        queued = self.trigger.maybe_queue(payload.user_id, count) \
            if count >= self.ready_threshold else False
        return IngestResult(storage_key=storage_key,
                            session_count=count, processing_queued=queued)
```

### Route (after)

```python
@router.post("/session", response_model=ReportSessionAcceptedResponse,
             status_code=status.HTTP_201_CREATED)
async def ingest_report_session(
    payload: ReportSessionPayload,
    service: ReportIngestionService = Depends(get_report_ingestion_service),
) -> ReportSessionAcceptedResponse:
    result = service.ingest(payload)
    return ReportSessionAcceptedResponse(
        user_id=payload.user_id,
        session_id=payload.session.session_id,
        stored=True,
        session_count=result.session_count,
        processing_queued=result.processing_queued,
        storage_key=result.storage_key,
    )
```

The DTO models, auth dependency, response shape, and storage path convention
from ADR-013 are **unchanged**. This is a pure relocation of the infra code plus
one decision seam.

## Future AWS Shape

Migration touches only the adapter and trigger — never the route or service:

| Concern | Today | Later (AWS) |
| --- | --- | --- |
| `RawSessionStore` | `LocalFileRawSessionStore` (disk) | `S3RawSessionStore` (`s3://.../raw/{user_id}/{session_id}.json`) |
| `ProcessingTrigger` | `NoopProcessingTrigger` | `EventBridgeTrigger` / `SqsTrigger` → Lambda runs `process.py` |
| Wiring | `get_report_ingestion_service()` returns local impls | same factory returns cloud impls (env-selected) |

Because raw sessions are immutable, the Lambda processor can run over S3-synced
inputs without changing the route/service contract.

## Superseded Processing Ownership (2026-06-06)

The ingestion boundary still stands, but report generation ownership changed in
[ADR-030](ADR-030-post-session-report-processing.md),
[ADR-031](ADR-031-report-end-to-end-workflow.md),
[ADR-032](ADR-032-sqs-first-hop-report-ingestion.md), and
[ADR-033](ADR-033-astro-report-frontend-data-source.md).

FastAPI is no longer a report processor. It stores raw sessions and uses
`ProcessingTrigger` only to no-op or enqueue work. The full attachment report is
produced by `infra/aws-lambda/attachment-report`:

- `report_processor.py` builds the deterministic website-ready shape.
- `attachment_analysis.py` owns Claude attachment-analysis enrichment.
- `handler.py` merges those into `results/{user_id}/attachment.json`.

The backend-side inline processor, processed-output store, local report sources,
and reprocess CLI were removed to avoid a duplicate preprocessing path.

### Current implemented layout

```text
mewi-backend/app/services/report/
    __init__.py
    store.py       # RawSessionStore + local/S3 raw-session impls
    trigger.py     # ProcessingTrigger + Noop/local-queue/SQS impls
    service.py     # ReportIngestionService + IngestResult
mewi-backend/app/api/deps.py   # get_report_ingestion_service() factory (env-selected paths)

infra/aws-lambda/attachment-report/
    handler.py
    report_processor.py
    attachment_analysis.py
    skills/attachment-analysis/SKILL.md
```

## Consequences

**Pros**
- Route stays a stable public contract; infra swaps behind the port.
- The 5-session readiness rule has one home (`ready_threshold` + `ProcessingTrigger`).
- Storage is unit-testable with an in-memory fake `RawSessionStore`, no disk.
- Matches the existing `app/services/*` package convention.

**Cons / tradeoffs**
- Adds small service/port files. Justified by the explicit Lambda-migration goal.
- Report generation now has a clear Lambda owner; changing the processed schema
  means updating Lambda `report_processor.py` and the frontend report schema.

## Migration Steps (done 2026-05-30)

1. ✅ Created `app/services/report/{processor,store,trigger,service}.py`, moving the
   four private helpers out of `report_router.py` into `LocalFileRawSessionStore`
   and the full `process.py` derivation into `processor.py`.
2. ✅ Added `get_report_ingestion_service()` factory in `app/api/deps.py`, reading
   `MEWI_REPORT_ROOT` / `MEWI_REPORT_RAW_SESSION_DIR` / `MEWI_REPORT_PROCESSED_DIR`
   / `MEWI_REPORT_SITE_DATA_DIR` / `MEWI_REPORT_USER_INFO` /
   `MEWI_REPORT_OVERRIDES_DIR` / `MEWI_REPORT_READY_THRESHOLD` from env.
3. ✅ Slimmed `report_router.py` to validation + delegation.
4. ✅ Added `tests/unit/services/test_report_ingestion.py` (in-memory + tmp-path
   fakes) asserting `session_count`, `processing_queued` across the threshold, and
   processed-output writes. Parity-checked byte-identical against the old
   `process.py` output for the demo user.
5. ✅ No Unity changes. No DTO changes. `process.py` removed from mewi-report (the
   backend now owns it); the legacy `/attachment/session` ATF path was deleted.
