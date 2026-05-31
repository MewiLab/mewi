from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import get_report_ingestion_service, verify_api_key
from app.models.report import ReportSessionAcceptedResponse, ReportSessionPayload
from app.services.report.service import ReportIngestionService
import logging
router = APIRouter(
    prefix="/report",
    tags=["report"],
    dependencies=[Depends(verify_api_key)],
)
logger = logging.getLogger(__name__)

@router.post(
    "/session",
    response_model=ReportSessionAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_report_session(
    payload: ReportSessionPayload,
    service: ReportIngestionService = Depends(get_report_ingestion_service),
) -> ReportSessionAcceptedResponse:
    """Validate one raw report session from Unity, store it, and derive the report.

    The route is a stable public contract: it only validates the DTO and
    delegates. Storage and processing live behind ports in
    ``app/services/report`` (ADR-014).
    """
    result = service.ingest(payload)
    logger.info(
        "Received raw session data; analysis attempted",
        extra={
            "user_id": payload.user_id,
            "session_id": payload.session.session_id,
            "processing_queued": result.processing_queued,
            "storage_key": result.storage_key,
        },
    )
    return ReportSessionAcceptedResponse(
        user_id=payload.user_id,
        session_id=payload.session.session_id,
        stored=True,
        session_count=result.session_count,
        processing_queued=result.processing_queued,
        storage_key=result.storage_key,
    )
