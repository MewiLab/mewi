from __future__ import annotations

from app.models.attachment import (
    AttachmentAnalysisResult,
    AttachmentSessionPayload,
)
from app.repositories.attachment_repo import AttachmentRepository
from app.services.attachment_map import atf
from app.services.attachment_preprocess import preprocess_attachment_session


class AttachmentWorker:
    """Runs the raw → features → ATF pipeline for one attachment session.

    Today this is invoked inline from the HTTP route, since sessions are small
    and externally triggered (see ADR-007). Encapsulating the steps here keeps
    the router thin and gives us one place to wrap a queue or background job
    around if analysis ever becomes slow or batch-based.
    """

    def __init__(self, repository: AttachmentRepository) -> None:
        self._repository = repository

    def process(self, payload: AttachmentSessionPayload) -> AttachmentAnalysisResult:
        raw_events = payload.raw_events()
        self._repository.save_raw_events(
            raw_events,
            cat_assigned_type=payload.cat_assigned_type,
        )
        features = preprocess_attachment_session(
            raw_events,
            cat_assigned_type=payload.cat_assigned_type,
        )
        self._repository.save_features(features)
        result = atf(features)
        self._repository.save_result(result)
        return result
