"""Report ingestion orchestration (ADR-014).

The one thin service between the HTTP route and infra. The route validates the
DTO and delegates here; this service owns the store calls and the
processing-readiness decision. It knows nothing about *how* storage or
processing are implemented — only the ports.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.report import ReportSessionPayload
from app.services.report.store import RawSessionStore
from app.services.report.trigger import ProcessingTrigger


@dataclass(frozen=True)
class IngestResult:
    storage_key: str
    session_count: int
    processing_queued: bool


class ReportIngestionService:
    def __init__(
        self,
        store: RawSessionStore,
        trigger: ProcessingTrigger,
        ready_threshold: int = 1,
    ) -> None:
        self._store = store
        self._trigger = trigger
        self._ready_threshold = max(ready_threshold, 1)

    def ingest(self, payload: ReportSessionPayload) -> IngestResult:
        storage_key = self._store.put(
            payload.user_id,
            payload.session.session_id,
            payload.model_dump(mode="json"),
        )
        count = self._store.count(payload.user_id)
        processed = (
            self._trigger.maybe_run(payload.user_id, count)
            if count >= self._ready_threshold
            else False
        )
        return IngestResult(
            storage_key=storage_key,
            session_count=count,
            processing_queued=processed,
        )
