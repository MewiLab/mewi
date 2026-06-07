"""Processing trigger port.

ADR-014 keeps the "is this user ready, and what runs the processor?" decision in
one place behind a ``Protocol``. Today processing runs in-process right after
ingest (``InlineProcessingTrigger``). Later this same seam becomes an
EventBridge / SQS hand-off to a Lambda running the *same* processor over
S3-synced raw sessions — the route and service never change.
"""

from __future__ import annotations

from typing import Protocol

from app.services.report.processor import process_report
from app.services.report.store import ProcessedReportStore, RawSessionStore, ReportSources


class ProcessingTrigger(Protocol):
    def maybe_run(self, user_id: str, session_count: int) -> bool: ...


class NoopProcessingTrigger:
    """Never processes. Kept for tests / environments that only want ingestion."""

    def maybe_run(self, user_id: str, session_count: int) -> bool:
        return False


class InlineProcessingTrigger:
    """Runs the report processor synchronously after a session is stored.

    Reads every stored raw session for the user, derives the processed report
    value data, and writes it to the processed/site stores so ``mewi-report``
    can render it without a manual ``process.py`` run.
    """

    def __init__(
        self,
        raw_store: RawSessionStore,
        processed_store: ProcessedReportStore,
        sources: ReportSources,
        attachment_mode: str = "agent",
    ) -> None:
        self._raw_store = raw_store
        self._processed_store = processed_store
        self._sources = sources
        self._attachment_mode = attachment_mode

    def maybe_run(self, user_id: str, session_count: int) -> bool:
        sessions = self._raw_store.load_sessions(user_id)
        if not sessions:
            return False
        report = process_report(
            user_id,
            sessions,
            self._sources.user_info(),
            self._sources.overrides(user_id),
            attachment_mode=self._attachment_mode,
        )
        self._processed_store.write(user_id, report)
        return True
