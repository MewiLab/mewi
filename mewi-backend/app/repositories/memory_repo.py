"""
Agent memory repository: Supabase persistence only.

The service layer owns meaning and fallback behavior. This module only maps
memory domain objects to rows and returns raw Supabase responses.
"""

import logging
from typing import Any, Dict, List

from postgrest.exceptions import APIError
from supabase import Client

from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent, TurnMemoryWrite
from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

TABLE = "agent_tick_history"
RAW_MEMORY_TABLE = "agent_memory_raw_events"
SHORT_TERM_MEMORY_TABLE = "agent_short_term_memories"


class MemoryRepository:
    def __init__(self, supabase: Client):
        self._db = supabase

    # ── Write ──────────────────────────────────────────────────

    def save_turn_memory(self, write: TurnMemoryWrite) -> dict[str, Any]:
        raw_row = self.save_raw_event(write.raw_event)
        short_term_rows = self.save_short_term_memories(
            write.raw_event.creature_id,
            write.raw_event.request_id,
            write.aspect_memories,
            raw_event_id=raw_row.get("id"),
        )
        return {
            "raw_event": raw_row,
            "short_term_memories": short_term_rows,
        }

    def save_raw_event(self, event: RawMemoryEvent) -> dict[str, Any]:
        row = {
            "creature_id": event.creature_id,
            "tick": event.tick,
            "request_id": event.request_id,
            "source": event.source,
            "event_type": event.event_type,
            "payload": event.payload,
        }
        try:
            response = self._db.table(RAW_MEMORY_TABLE).insert(row).execute()
            return _first_row(response.data)
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase raw memory insert error: %s", message)
            raise DatabaseError(message) from exc

    def save_short_term_memories(
        self,
        creature_id: str,
        request_id: str,
        memories: list[AspectMemory],
        *,
        raw_event_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            {
                "raw_event_id": raw_event_id,
                "creature_id": creature_id,
                "tick": memory.tick,
                "request_id": request_id,
                "memory_kind": memory.memory_kind,
                "aspect": memory.aspect,
                "text": memory.text,
                "salience": memory.salience,
                "evidence": memory.evidence,
            }
            for memory in memories
            if memory.text.strip()
        ]
        if not rows:
            return []

        try:
            response = self._db.table(SHORT_TERM_MEMORY_TABLE).insert(rows).execute()
            return response.data or []
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase short-term memory insert error: %s", message)
            raise DatabaseError(message) from exc

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

    def load_recent_raw_events(
        self,
        creature_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        try:
            response = (
                self._db.table(RAW_MEMORY_TABLE)
                .select("*")
                .eq("creature_id", creature_id)
                .order("tick", desc=True)
                .limit(limit)
                .execute()
            )
            return list(reversed(response.data or []))
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase raw memory select error: %s", message)
            raise DatabaseError(message) from exc

    def load_recent_short_term_memories(
        self,
        creature_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        try:
            response = (
                self._db.table(SHORT_TERM_MEMORY_TABLE)
                .select("*")
                .eq("creature_id", creature_id)
                .order("tick", desc=True)
                .limit(limit)
                .execute()
            )
            return list(reversed(response.data or []))
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase short-term memory select error: %s", message)
            raise DatabaseError(message) from exc

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


def _first_row(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}
