"""Report ingestion orchestration (ADR-014).

The one thin service between the HTTP route and infra. The route validates the
DTO and delegates here; this service owns the store calls and the
processing-readiness decision. It knows nothing about *how* storage or
processing are implemented — only the ports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.report import ReportCardResponse, ReportProduct, ReportSessionPayload
from app.services.report.store import ReportResultStore, RawSessionStore, safe_segment
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


class ReportReadService:
    """Read finished report products from the result store.

    This service is deliberately read-only. It does not enqueue jobs, run
    processors, call LLMs, or compose new report products.
    """

    def __init__(self, store: ReportResultStore) -> None:
        self._store = store

    def load(self, user_id: str, product: ReportProduct = "attachment") -> dict[str, Any]:
        return self._store.get(user_id, product)

    def list_cards(self, product: ReportProduct = "attachment") -> list[ReportCardResponse]:
        cards = [_card_from_report(report, product) for report in self._store.list(product)]
        return sorted(cards, key=lambda card: card.last_seen, reverse=True)

    def card_for(self, user_id: str, product: ReportProduct = "attachment") -> ReportCardResponse:
        return _card_from_report(self.load(user_id, product), product)


def _card_from_report(report: dict[str, Any], product: ReportProduct) -> ReportCardResponse:
    user = report.get("user") if isinstance(report.get("user"), dict) else {}
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}

    user_id = str(report.get("user_id") or user.get("id") or "").strip()
    if not user_id:
        user_id = "unknown"

    route_source = user.get("handle") or user.get("report_slug") or user_id
    display_name = str(user.get("display_name") or user.get("handle") or user_id)

    return ReportCardResponse(
        user_id=user_id,
        data_file_id=user_id,
        route_id=safe_segment(str(route_source)),
        display_name=display_name,
        product=product,
        last_seen=str(meta.get("last_seen") or ""),
        sessions=_int_or_zero(meta.get("sessions")),
        total_events=_int_or_zero(meta.get("total_events")),
        primary_bond=str(summary.get("primary_bond") or ""),
    )


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
