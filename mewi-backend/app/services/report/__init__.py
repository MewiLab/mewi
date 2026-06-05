"""Report ingestion + processing service (ADR-014).

Owns the raw→value report pipeline that the backend exposes at
``POST /api/v1/report/session``:

    route -> ReportIngestionService.ingest(payload)
               -> RawSessionStore.put / count        (store.py)
               -> ProcessingTrigger.maybe_run        (trigger.py)
                    -> process_report(...)            (processor.py)
                    -> ProcessedReportStore.write     (store.py)

``mewi-report`` is render-only: it reads the processed JSON this service writes.
"""

from app.services.report.processor import process_report
from app.services.report.service import IngestResult, ReportIngestionService

__all__ = ["IngestResult", "ReportIngestionService", "process_report"]
