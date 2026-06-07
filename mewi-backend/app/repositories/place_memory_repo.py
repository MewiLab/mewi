from __future__ import annotations

import asyncio
import logging
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client

from app.agent.schemas.place_memory_schema import PlaceMemoryEntry, PlaceMemoryOverlay
from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

PLACE_MEMORY_TABLE = "agent_place_memories"
PLACE_MEMORY_STATE_TABLE = "agent_place_memory_state"


class PlaceMemoryRepository:
    """Permanent Supabase store for per-creature place coverage."""

    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    async def record_visit(
        self,
        creature_id: str,
        zone_id: str,
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        await asyncio.to_thread(
            self._record_visit_sync,
            creature_id,
            zone_id,
            observed_at,
            request_id,
        )

    async def record_seen_places(
        self,
        creature_id: str,
        zone_ids: list[str],
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        await asyncio.to_thread(
            self._record_seen_places_sync,
            creature_id,
            zone_ids,
            observed_at,
            request_id,
        )

    async def load_overlay(self, creature_id: str) -> PlaceMemoryOverlay:
        rows = await asyncio.to_thread(self._load_rows_sync, creature_id)
        entries = {
            entry.zone_id: entry
            for row in rows
            if (entry := PlaceMemoryEntry.from_dict(row)).zone_id
        }
        return PlaceMemoryOverlay(entries=entries)

    def _record_visit_sync(
        self,
        creature_id: str,
        zone_id: str,
        observed_at: float,
        request_id: str,
    ) -> None:
        creature_id = _clean_text(creature_id)
        zone_id = _clean_text(zone_id)
        if not creature_id or not zone_id:
            return

        state = self._load_state_sync(creature_id)
        current = self._load_entry_sync(creature_id, zone_id)
        visit_count = int((current or {}).get("visit_count") or 0)
        if _clean_text(state.get("last_zone_id")).lower() != zone_id.lower():
            visit_count += 1

        row = {
            "creature_id": creature_id,
            "zone_id": zone_id,
            "visit_count": visit_count,
            "last_visited_at": observed_at,
            "last_seen_at": observed_at,
            "familiarity": min(1.0, visit_count / 8),
            "last_arrival_request_id": request_id,
        }
        self._upsert_entry_sync(row)
        self._upsert_state_sync({
            "creature_id": creature_id,
            "last_zone_id": zone_id,
            "last_observed_at": observed_at,
            "last_request_id": request_id,
        })

    def _record_seen_places_sync(
        self,
        creature_id: str,
        zone_ids: list[str],
        observed_at: float,
        request_id: str,
    ) -> None:
        creature_id = _clean_text(creature_id)
        if not creature_id:
            return

        for zone_id in _dedupe(zone_ids):
            current = self._load_entry_sync(creature_id, zone_id)
            if current:
                row = {
                    **current,
                    "last_seen_at": observed_at,
                    "last_arrival_request_id": (
                        current.get("last_arrival_request_id") or request_id
                    ),
                }
            else:
                row = {
                    "creature_id": creature_id,
                    "zone_id": zone_id,
                    "visit_count": 0,
                    "last_visited_at": None,
                    "last_seen_at": observed_at,
                    "familiarity": 0.0,
                    "last_arrival_request_id": request_id,
                }
            self._upsert_entry_sync(row)

    def _load_entry_sync(self, creature_id: str, zone_id: str) -> dict[str, Any]:
        try:
            response = (
                self._db.table(PLACE_MEMORY_TABLE)
                .select("*")
                .eq("creature_id", creature_id)
                .eq("zone_id", zone_id)
                .limit(1)
                .execute()
            )
            return _first_row(response.data)
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase place memory select error: %s", message)
            raise DatabaseError(message) from exc

    def _load_rows_sync(self, creature_id: str) -> list[dict[str, Any]]:
        try:
            response = (
                self._db.table(PLACE_MEMORY_TABLE)
                .select("*")
                .eq("creature_id", creature_id)
                .order("last_seen_at", desc=True)
                .execute()
            )
            return response.data or []
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase place memory overlay select error: %s", message)
            raise DatabaseError(message) from exc

    def _load_state_sync(self, creature_id: str) -> dict[str, Any]:
        try:
            response = (
                self._db.table(PLACE_MEMORY_STATE_TABLE)
                .select("*")
                .eq("creature_id", creature_id)
                .limit(1)
                .execute()
            )
            return _first_row(response.data)
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase place memory state select error: %s", message)
            raise DatabaseError(message) from exc

    def _upsert_entry_sync(self, row: dict[str, Any]) -> None:
        try:
            (
                self._db.table(PLACE_MEMORY_TABLE)
                .upsert(row, on_conflict="creature_id,zone_id")
                .execute()
            )
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase place memory upsert error: %s", message)
            raise DatabaseError(message) from exc

    def _upsert_state_sync(self, row: dict[str, Any]) -> None:
        try:
            (
                self._db.table(PLACE_MEMORY_STATE_TABLE)
                .upsert(row, on_conflict="creature_id")
                .execute()
            )
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase place memory state upsert error: %s", message)
            raise DatabaseError(message) from exc


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _first_row(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}
