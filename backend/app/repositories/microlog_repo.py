"""
Microlog repository — pure data-access layer.

Rules:
  - No business logic here (no embedding, no side effects).
  - Receives the Supabase client as a constructor arg (injected by deps).
  - Returns raw dicts; the service layer converts to Pydantic models.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi.encoders import jsonable_encoder
from postgrest.exceptions import APIError
from supabase import Client

from app.core.exceptions import DatabaseError, NotFoundError
from app.models.microlog import MicrologInDB, MicrologUpdate

logger = logging.getLogger(__name__)

TABLE = "micrologs"


class MicrologRepository:
    def __init__(self, supabase: Client):
        self._db = supabase

    # ── Write ─────────────────────────────────────────────────
    def create(self, data: MicrologInDB) -> Dict[str, Any]:
        payload = jsonable_encoder(
            data.model_dump(exclude_none=True)
        )
        try:
            response = self._db.table(TABLE).insert(payload).execute()
            if not response.data:
                raise DatabaseError("Insert returned empty data")
            return response.data[0]
        except APIError as exc:
            logger.error("Supabase insert error: %s", exc.message)
            raise DatabaseError(exc.message) from exc

    def update(self, log_id: str, patch: MicrologUpdate) -> Dict[str, Any]:
        payload = jsonable_encoder(
            patch.model_dump(exclude_none=True)
        )
        try:
            response = (
                self._db.table(TABLE)
                .update(payload)
                .eq("id", log_id)
                .execute()
            )
            if not response.data:
                raise NotFoundError("Microlog")
            return response.data[0]
        except APIError as exc:
            logger.error("Supabase update error: %s", exc.message)
            raise DatabaseError(exc.message) from exc

    # ── Read ──────────────────────────────────────────────────
    def get_by_user(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        response = (
            self._db.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return response.data

    def get_by_id(self, log_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self._db.table(TABLE)
            .select("*")
            .eq("id", log_id)
            .maybe_single()
            .execute()
        )
        return response.data
