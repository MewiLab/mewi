from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import SupabaseDep, verify_api_key
from app.models.attachment import AttachmentAnalysisResult, AttachmentSessionPayload
from app.repositories.attachment_repo import AttachmentRepository
from app.workers.attachment_worker import AttachmentWorker

router = APIRouter(
    prefix="/attachment",
    tags=["attachment"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/session",
    response_model=AttachmentAnalysisResult,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_attachment_session(
    payload: AttachmentSessionPayload,
    supabase: SupabaseDep,
) -> AttachmentAnalysisResult:
    """Store raw logs, derive features, classify with transparent ATF rules."""
    worker = AttachmentWorker(AttachmentRepository(supabase))
    return worker.process(payload)
