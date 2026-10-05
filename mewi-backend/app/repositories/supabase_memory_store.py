"""Supabase-backed :class:`~app.agent.memory.memory_store.MemoryStore`.

Durable recent + keyword recall over plain Postgres rows. Maps memory domain
objects to rows and back; owns no policy. Sync Supabase calls are offloaded to
a thread so they never block the event loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client

from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent, TurnMemoryWrite
from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

RAW_MEMORY_TABLE = "agent_memory_raw_events"
SHORT_TERM_MEMORY_TABLE = "agent_short_term_memories"


class SupabaseMemoryStore:
    """MemoryStore backed by Supabase rows."""

    def __init__(self, supabase: Client):
        self._db = supabase

    # ── MemoryStore protocol ───────────────────────────────────

    async def record_turn(self, write: TurnMemoryWrite) -> None:
        await asyncio.to_thread(self._save_turn_memory, write)

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Keyword recall: short-term memories whose text matches ``query``.

        Falls back to the most recent memories when ``query`` is empty.
        """
        return await asyncio.to_thread(self._search, query, creature_id, limit)

    # ── sync internals ─────────────────────────────────────────

    def _save_turn_memory(self, write: TurnMemoryWrite) -> dict[str, Any]:
        raw_row = self._save_raw_event(write.raw_event)
        self._save_short_term_memories(
            write.raw_event.creature_id,
            write.raw_event.request_id,
            write.aspect_memories,
            raw_event_id=raw_row.get("id"),
        )
        return raw_row

    def _save_raw_event(self, event: RawMemoryEvent) -> dict[str, Any]:
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

    def _save_short_term_memories(
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

    def _search(self, query: str, creature_id: str, limit: int) -> list[dict[str, Any]]:
        try:
            builder = (
                self._db.table(SHORT_TERM_MEMORY_TABLE)
                .select("*")
                .eq("creature_id", creature_id)
            )
            if query.strip():
                builder = builder.ilike("text", f"%{query.strip()}%")
            response = builder.order("tick", desc=True).limit(limit).execute()
            return list(reversed(response.data or []))
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase memory search error: %s", message)
            raise DatabaseError(message) from exc


def _first_row(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}
