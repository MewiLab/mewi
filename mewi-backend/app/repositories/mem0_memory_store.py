"""mem0-backed :class:`~app.agent.memory.memory_store.MemoryStore`.

Graph + vector memory: mem0 extracts salient facts from each turn, stores
relations in Neo4j and vectors in pgvector (Supabase), and serves
semantic + graph recall.

``mem0`` is an *optional* dependency (extra: ``graph-memory``) and is imported
lazily, so the app runs without it until graph memory is enabled.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent.memory.memory_models import TurnMemoryWrite

logger = logging.getLogger(__name__)


class Mem0MemoryStore:
    """MemoryStore backed by a configured ``mem0.Memory`` instance."""

    def __init__(self, memory: Any):
        self._mem = memory  # mem0.Memory

    @classmethod
    def from_settings(cls, *, llm, embedding, memory) -> "Mem0MemoryStore":
        """Build from app settings blocks (``llm``, ``embedding``, ``memory``).

        Imports mem0 lazily; raises a clear error if the extra isn't installed.
        """
        try:
            from mem0 import Memory  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Graph memory is enabled but 'mem0ai' is not installed. "
                "Install the extra: uv sync --extra graph-memory"
            ) from exc
        return cls(Memory.from_config(_build_config(llm, embedding, memory)))

    async def record_turn(self, write: TurnMemoryWrite) -> None:
        await asyncio.to_thread(self._add, write)

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._search, query, creature_id, limit)

    # ── sync internals ─────────────────────────────────────────

    def _add(self, write: TurnMemoryWrite) -> None:
        creature_id = write.raw_event.creature_id
        for memory in write.aspect_memories:
            if not memory.text.strip():
                continue
            self._mem.add(
                memory.text,
                user_id=creature_id,
                metadata={"aspect": memory.aspect, "tick": memory.tick},
            )

    def _search(self, query: str, creature_id: str, limit: int) -> list[dict[str, Any]]:
        result = self._mem.search(query, user_id=creature_id, limit=limit)
        # mem0 returns either {"results": [...]} or a bare list across versions.
        if isinstance(result, dict):
            return result.get("results", [])
        return result or []


def _build_config(llm, embedding, memory) -> dict[str, Any]:
    """Assemble a mem0 config dict from app settings.

    NOTE: shape follows mem0's documented config; verify against the installed
    mem0 version before enabling in production.
    """
    config: dict[str, Any] = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": llm.model,
                "api_key": llm.api_key,
                **({"openai_base_url": llm.base_url} if llm.base_url else {}),
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": embedding.model,
                "api_key": embedding.api_key or llm.api_key,
                **({"openai_base_url": embedding.base_url} if embedding.base_url else {}),
            },
        },
        "graph_store": {
            "provider": "neo4j",
            "config": {
                "url": memory.neo4j_url,
                "username": memory.neo4j_username,
                "password": memory.neo4j_password,
            },
        },
    }
    if memory.pgvector_dsn:
        config["vector_store"] = {
            "provider": "pgvector",
            "config": {"connection_string": memory.pgvector_dsn},
        }
    return config
