"""
Agent memory repository — pure data-access layer for tick history.

Rules:
  - No business logic here (no serialization decisions, no side effects).
  - Receives the Supabase client as a constructor arg (injected by deps).
  - Returns raw dicts; the service layer converts to domain objects.

Expected Supabase table: agent_tick_history
  id          uuid (PK, default gen_random_uuid())
  creature_id text  NOT NULL
  tick        int   NOT NULL
  perception  jsonb NOT NULL
  threat_level int  NOT NULL DEFAULT 0
  created_at  timestamptz DEFAULT now()
"""

import logging
from typing import Any, Dict, List

from postgrest.exceptions import APIError
from supabase import Client

from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

TABLE = "agent_tick_history"


class MemoryRepository:
    def __init__(self, supabase: Client):
        self._db = supabase

    # ── Write ──────────────────────────────────────────────────

    def save_tick(
        self,
        creature_id: str,
        tick: int,
        perception: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "creature_id": creature_id,
            "tick": tick,
            "perception": perception,
            "threat_level": perception.get("threat_level", 0),
        }
        try:
            response = self._db.table(TABLE).insert(payload).execute()
            if not response.data:
                raise DatabaseError("Insert returned empty data")
            return response.data[0]
        except APIError as exc:
            logger.error("Supabase insert error: %s", exc.message)
            raise DatabaseError(exc.message) from exc

    # ── Read ───────────────────────────────────────────────────

    def load_recent_ticks(
        self,
        creature_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Returns rows in ascending tick order (oldest first) so the caller
        can replay them into memory chronologically.
        """
        try:
            response = (
                self._db.table(TABLE)
                .select("*")
                .eq("creature_id", creature_id)
                .order("tick", desc=True)
                .limit(limit)
                .execute()
            )
            # DB returns newest-first; reverse for chronological replay
            return list(reversed(response.data))
        except APIError as exc:
            logger.error("Supabase select error: %s", exc.message)
            raise DatabaseError(exc.message) from exc
