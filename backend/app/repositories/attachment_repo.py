from __future__ import annotations

import logging
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client

from app.core.exceptions import DatabaseError
from app.models.attachment import (
    AttachmentAnalysisResult,
    AttachmentSessionFeatures,
    CatAssignedType,
    RawAttachmentEvent,
)

logger = logging.getLogger(__name__)

RAW_EVENTS_TABLE = "attachment_raw_events"
FEATURES_TABLE = "attachment_session_features"
RESULTS_TABLE = "attachment_results"


class AttachmentRepository:
    """Supabase persistence for the auditable attachment pipeline."""

    def __init__(self, supabase: Client):
        self._db = supabase

    def save_raw_events(
        self,
        events: list[RawAttachmentEvent],
        *,
        cat_assigned_type: CatAssignedType,
    ) -> list[dict[str, Any]]:
        rows = [
            {
                **event.model_dump(mode="json"),
                "cat_assigned_type": cat_assigned_type.value,
            }
            for event in events
        ]
        if not rows:
            return []

        try:
            response = self._db.table(RAW_EVENTS_TABLE).insert(rows).execute()
            return response.data or []
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase attachment raw insert error: %s", message)
            raise DatabaseError(message) from exc

    def save_features(self, features: AttachmentSessionFeatures) -> dict[str, Any]:
        row = features.model_dump(mode="json")
        try:
            response = (
                self._db.table(FEATURES_TABLE)
                .upsert(row, on_conflict="session_id,cat_id")
                .execute()
            )
            return _first_row(response.data)
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase attachment features upsert error: %s", message)
            raise DatabaseError(message) from exc

    def save_result(self, result: AttachmentAnalysisResult) -> dict[str, Any]:
        row = {
            "session_id": str(result.session_id),
            "cat_id": result.cat_id,
            "cat_assigned_type": result.cat_assigned_type.value,
            "player_attachment_estimate": result.player_attachment_estimate.value,
            "scores": result.scores,
            "confidence": result.confidence.value,
            "n_events": result.n_events,
            "features": result.features.model_dump(mode="json"),
            "rule_trace": result.rule_trace,
        }
        try:
            response = (
                self._db.table(RESULTS_TABLE)
                .upsert(row, on_conflict="session_id,cat_id")
                .execute()
            )
            return _first_row(response.data)
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase attachment result upsert error: %s", message)
            raise DatabaseError(message) from exc


def _first_row(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}
