"""Supabase-backed semantic summary memory store.

ADR-034 keeps low-level events out of Supabase. This store owns reconciled
semantic meaning: consolidated ``AspectMemory(memory_kind="summary")`` rows are
added, reinforced, or superseded so durable memory stays small and current.
Sync Supabase calls are offloaded to a thread so they never block the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client

from app.agent.memory.memory_models import AspectMemory, TurnMemoryWrite
from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

SUMMARY_MEMORY_TABLE = "agent_memory_summaries"

EmbeddingFn = Callable[[str], Sequence[float]]

_VECTOR_LIMIT = 1536
_REINFORCE_SALIENCE_STEP = 0.03
_NOOP_SIMILARITY = 0.96
_SUPERSEDE_SIMILARITY = 0.72
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class SupabaseMemoryStore:
    """MemoryStore backed by Supabase rows."""

    def __init__(
        self,
        supabase: Client,
        *,
        embed_text: EmbeddingFn | None = None,
    ):
        self._db = supabase
        self._embed_text = embed_text

    # ── MemoryStore protocol ───────────────────────────────────

    async def record_turn(self, write: TurnMemoryWrite) -> None:
        await asyncio.to_thread(self._save_turn_memory, write)

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
        now_tick: int | None = None,
    ) -> list[dict[str, Any]]:
        """Recall active semantic facts, preferring vector relevance when wired."""
        return await asyncio.to_thread(self._search, query, creature_id, limit, now_tick)

    # ── sync internals ─────────────────────────────────────────

    def _save_turn_memory(self, write: TurnMemoryWrite) -> list[dict[str, Any]]:
        return self._save_summary_memories(
            write.raw_event.creature_id,
            write.aspect_memories,
        )

    def _save_summary_memories(
        self,
        creature_id: str,
        memories: list[AspectMemory],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for memory in memories:
            if memory.memory_kind != "summary" or not memory.text.strip():
                continue
            rows.extend(self._reconcile_memory(creature_id, memory))
        return rows

    def _reconcile_memory(
        self,
        creature_id: str,
        memory: AspectMemory,
    ) -> list[dict[str, Any]]:
        row = _summary_row(creature_id, memory)
        embedding = self._embed(memory.text)
        if embedding:
            row["embedding"] = embedding

        try:
            candidates = self._candidate_summaries(
                text=memory.text,
                creature_id=creature_id,
                aspect=memory.aspect,
                embedding=embedding,
                limit=5,
            )
            best = _best_candidate(memory.text, candidates)
            if best is None:
                return self._insert_summary(row)

            best_row = best["row"]
            best_id = str(best_row.get("id") or "")
            if _normalized_text(best_row.get("text")) == _normalized_text(memory.text) or best["score"] >= _NOOP_SIMILARITY:
                self._reinforce_summary(best_id, memory, existing=best["row"])
                return [{**best["row"], "reconcile_action": "noop"}]

            if best["score"] >= _SUPERSEDE_SIMILARITY:
                inserted = self._insert_summary(row)
                new_id = str(_first_row(inserted).get("id") or "")
                if best_id and new_id:
                    self._supersede_summary(best_id, new_id)
                return inserted

            return self._insert_summary(row)
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase summary memory reconcile error: %s", message)
            raise DatabaseError(message) from exc

    def _search(
        self,
        query: str,
        creature_id: str,
        limit: int,
        now_tick: int | None,
    ) -> list[dict[str, Any]]:
        try:
            embedding = self._embed(query)
            if embedding:
                rows = self._vector_search(
                    embedding=embedding,
                    creature_id=creature_id,
                    aspect="",
                    limit=limit,
                )
                if rows:
                    scored = _score_rows(rows, query=query, now_tick=now_tick)
                    self._reinforce_recalled(scored, now_tick=now_tick)
                    return scored[:limit]
            rows = self._search_summaries(query, creature_id, limit)
            scored = _score_rows(rows, query=query, now_tick=now_tick)
            self._reinforce_recalled(scored, now_tick=now_tick)
            return scored[:limit]
        except APIError as exc:
            message = getattr(exc, "message", str(exc))
            logger.error("Supabase summary memory search error: %s", message)
            raise DatabaseError(message) from exc

    def _candidate_summaries(
        self,
        *,
        text: str,
        creature_id: str,
        aspect: str,
        embedding: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        if embedding:
            rows = self._vector_search(
                embedding=embedding,
                creature_id=creature_id,
                aspect=aspect,
                limit=limit,
            )
            if rows:
                return rows
        return self._search_summaries(text, creature_id, limit, aspect=aspect)

    def _search_summaries(
        self,
        query: str,
        creature_id: str,
        limit: int,
        *,
        aspect: str = "",
    ) -> list[dict[str, Any]]:
        builder = (
            self._db.table(SUMMARY_MEMORY_TABLE)
            .select("*")
            .eq("creature_id", creature_id)
            .eq("is_active", True)
        )
        if aspect:
            builder = builder.eq("aspect", aspect)
        if query.strip():
            builder = builder.ilike("text", f"%{_keyword_probe(query)}%")
        response = builder.order("tick_end", desc=True).limit(limit).execute()
        return response.data or []

    def _vector_search(
        self,
        *,
        embedding: list[float],
        creature_id: str,
        aspect: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        rpc = getattr(self._db, "rpc", None)
        if not callable(rpc):
            return []
        try:
            response = rpc(
                "match_agent_memory_summaries",
                {
                    "query_embedding": embedding,
                    "match_creature_id": creature_id,
                    "match_count": limit,
                    "match_aspect": aspect,
                },
            ).execute()
            return response.data or []
        except APIError:
            raise
        except Exception:
            logger.debug("Supabase vector memory search unavailable", exc_info=True)
            return []

    def _insert_summary(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._db.table(SUMMARY_MEMORY_TABLE).insert([row]).execute()
        return response.data or []

    def _reinforce_summary(
        self,
        row_id: str,
        memory: AspectMemory,
        *,
        existing: dict[str, Any],
    ) -> None:
        if not row_id:
            return
        tick_end = int(memory.evidence.get("tick_end", memory.tick))
        salience = max(_float(existing.get("salience"), 0.0), float(memory.salience or 0.0))
        patch = {
            "last_active_tick": tick_end,
            "salience": min(1.0, salience + _REINFORCE_SALIENCE_STEP),
            "updated_at": _utc_now(),
        }
        self._db.table(SUMMARY_MEMORY_TABLE).update(patch).eq("id", row_id).execute()

    def _supersede_summary(self, old_id: str, new_id: str) -> None:
        patch = {
            "is_active": False,
            "superseded_by": new_id,
            "updated_at": _utc_now(),
        }
        self._db.table(SUMMARY_MEMORY_TABLE).update(patch).eq("id", old_id).execute()

    def _reinforce_recalled(self, rows: list[dict[str, Any]], *, now_tick: int | None) -> None:
        if now_tick is None:
            return
        for row in rows:
            row_id = str(row.get("id") or "")
            if not row_id:
                continue
            salience = _float(row.get("salience"), 0.0)
            patch = {
                "last_active_tick": now_tick,
                "salience": min(1.0, salience + _REINFORCE_SALIENCE_STEP),
                "updated_at": _utc_now(),
            }
            self._db.table(SUMMARY_MEMORY_TABLE).update(patch).eq("id", row_id).execute()

    def _embed(self, text: str) -> list[float]:
        if self._embed_text is None or not text.strip():
            return []
        try:
            values = [float(value) for value in self._embed_text(text)]
        except Exception:
            logger.warning("Summary embedding failed; using keyword recall", exc_info=True)
            return []
        if not values:
            return []
        if len(values) > _VECTOR_LIMIT:
            return values[:_VECTOR_LIMIT]
        if len(values) < _VECTOR_LIMIT:
            values = [*values, *([0.0] * (_VECTOR_LIMIT - len(values)))]
        return values


def _first_row(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


def _summary_row(creature_id: str, memory: AspectMemory) -> dict[str, Any]:
    tick_start = int(memory.evidence.get("tick_start", memory.tick))
    tick_end = int(memory.evidence.get("tick_end", memory.tick))
    return {
        "creature_id": creature_id,
        "aspect": memory.aspect,
        "memory_kind": memory.memory_kind,
        "text": memory.text,
        "tick_start": tick_start,
        "tick_end": tick_end,
        "source_count": int(memory.evidence.get("source_count", 0)),
        "salience": memory.salience,
        "evidence": memory.evidence,
        "is_active": True,
        "last_active_tick": tick_end,
    }


def _best_candidate(text: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for row in rows:
        vector_score = _float(row.get("similarity"), -1.0)
        lexical_score = _lexical_similarity(text, str(row.get("text") or ""))
        score = max(vector_score, lexical_score)
        candidate = {"row": row, "score": score}
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def _score_rows(
    rows: list[dict[str, Any]],
    *,
    query: str,
    now_tick: int | None,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in rows:
        relevance = max(
            _float(row.get("similarity"), 0.0),
            _lexical_similarity(query, str(row.get("text") or "")),
        )
        salience = _float(row.get("salience"), 0.0)
        recency = _recency_score(row, now_tick=now_tick)
        score = 0.65 * relevance + 0.25 * recency + 0.10 * salience
        scored.append({**row, "score": score})
    scored.sort(
        key=lambda row: (
            _float(row.get("score"), 0.0),
            int(row.get("tick_end") or 0),
        ),
        reverse=True,
    )
    return scored


def _recency_score(row: dict[str, Any], *, now_tick: int | None) -> float:
    if now_tick is None:
        return 1.0
    last_tick = int(row.get("last_active_tick") or row.get("tick_end") or 0)
    if last_tick <= 0:
        return 0.0
    age = max(0, now_tick - last_tick)
    return math.exp(-age / 128.0)


def _lexical_similarity(left: str, right: str) -> float:
    a = set(_tokens(left))
    b = set(_tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _keyword_probe(text: str) -> str:
    tokens = _tokens(text)
    if not tokens:
        return text.strip()
    meaningful = [token for token in tokens if len(token) > 2]
    return (meaningful or tokens)[0]


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
