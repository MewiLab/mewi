"""Report ingestion service.

Owns the raw-session ingestion path that the backend exposes at
``POST /api/v1/report/session``:

    route -> ReportIngestionService.ingest(payload)
               -> RawSessionStore.put / count        (store.py)
               -> ProcessingTrigger.maybe_run        (trigger.py)
                    -> enqueue/noop; Lambda owns report generation

``mewi-report`` is render-only: it reads processed JSON exposed by the backend
read gateway after the Lambda writes it to S3.
"""

from app.services.report.service import IngestResult, ReportIngestionService

__all__ = ["IngestResult", "ReportIngestionService"]
