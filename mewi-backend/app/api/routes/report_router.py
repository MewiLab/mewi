from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    ReportPrincipalDep,
    get_report_ingestion_service,
    get_report_read_service,
    verify_api_key,
)
from app.core.auth import authorize_report_user
from app.models.report import (
    ReportCardResponse,
    ReportProduct,
    ReportSessionAcceptedResponse,
    ReportSessionPayload,
)
from app.services.report.service import ReportIngestionService, ReportReadService
from app.services.report.store import ReportResultInvalid, ReportResultNotFound

router = APIRouter(
    prefix="/report",
    tags=["report"],
)
logger = logging.getLogger(__name__)


@router.post(
    "/session",
    response_model=ReportSessionAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
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


@router.get("/", response_model=list[ReportCardResponse])
async def list_report_cards(
    principal: ReportPrincipalDep,
    product: ReportProduct = "attachment",
    service: ReportReadService = Depends(get_report_read_service),
) -> list[ReportCardResponse]:
    """List report cards the caller is allowed to see.

    Admin tokens see the directory. Player tokens see only their own card, and
    get an empty list until their report product exists.
    """
    if principal.admin:
        return service.list_cards(product)
    try:
        return [service.card_for(principal.user_id, product)]
    except ReportResultNotFound:
        return []


@router.get("/me/{product}", response_model=dict[str, Any])
async def read_my_report(
    product: ReportProduct,
    principal: ReportPrincipalDep,
    service: ReportReadService = Depends(get_report_read_service),
) -> dict[str, Any]:
    """Read the caller's report product; identity comes from the token subject."""
    return _read_report_or_raise(service, principal.user_id, product)


@router.get("/{user_id}/{product}", response_model=dict[str, Any])
async def read_report_for_user(
    user_id: str,
    product: ReportProduct,
    principal: ReportPrincipalDep,
    service: ReportReadService = Depends(get_report_read_service),
) -> dict[str, Any]:
    """Read a report by URL locator after admin-or-self authorization."""
    authorized_user_id = authorize_report_user(principal, user_id)
    return _read_report_or_raise(service, authorized_user_id, product)


def _read_report_or_raise(
    service: ReportReadService,
    user_id: str,
    product: ReportProduct,
) -> dict[str, Any]:
    try:
        return service.load(user_id, product)
    except ReportResultNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report product was not found.",
        ) from exc
    except ReportResultInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Report product JSON is invalid.",
        ) from exc
