"""mem0-backed :class:`~app.agent.memory.memory_store.MemoryStore`.

Semantic/vector memory: mem0 extracts salient facts from each turn, stores
vectors in pgvector (Supabase), and serves semantic recall.

Neo4j settings are accepted by app config, but the installed ``mem0ai`` package
must expose a ``graph_store`` config field before this adapter can pass them
through. ``mem0ai==2.0.4`` does not, so the adapter validates and drops that
block with a warning instead of silently relying on ignored config.

``mem0`` is an *optional* dependency (extra: ``graph-memory``) and is imported
lazily, so the app runs without it until graph memory is enabled.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
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
        _ensure_mem0_dir()
        try:
            from mem0 import Memory  # type: ignore
            from mem0.configs.base import MemoryConfig  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Graph memory is enabled but 'mem0ai' is not installed. "
                "Install the extra: uv sync --extra graph-memory"
            ) from exc

        config = _build_config(llm, embedding, memory)
        config = _validate_config_for_installed_mem0(config, MemoryConfig)
        return cls(Memory.from_config(config))

    async def record_turn(self, write: TurnMemoryWrite) -> None:
        await asyncio.to_thread(self._add, write)

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
        now_tick: int | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._search, query, creature_id, limit)

    # ── sync internals ─────────────────────────────────────────

    def _add(self, write: TurnMemoryWrite) -> None:
        creature_id = write.raw_event.creature_id
        for memory in write.aspect_memories:
            if memory.memory_kind != "summary" or not memory.text.strip():
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

    The shape is intentionally isolated here because mem0 config keys drift
    between releases. ``_validate_config_for_installed_mem0`` checks this dict
    against the installed ``MemoryConfig`` before the app starts mem0.
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
    }
    if memory.neo4j_url and memory.neo4j_password:
        config["graph_store"] = {
            "provider": "neo4j",
            "config": {
                "url": memory.neo4j_url,
                "username": memory.neo4j_username,
                "password": memory.neo4j_password,
            },
        }
    if memory.pgvector_dsn:
        config["vector_store"] = {
            "provider": "pgvector",
            "config": {
                "connection_string": memory.pgvector_dsn,
                "collection_name": "mewi_memories",
            },
        }
    return config


def _validate_config_for_installed_mem0(config: dict[str, Any], memory_config_cls) -> dict[str, Any]:
    """Return only config keys accepted by the installed mem0 ``MemoryConfig``."""
    fields = set(getattr(memory_config_cls, "model_fields", {}).keys())
    accepted = dict(config)
    if "graph_store" in accepted and "graph_store" not in fields:
        logger.warning(
            "Installed mem0 MemoryConfig has no graph_store field; Neo4j memory "
            "settings will not be used by mem0. Semantic pgvector recall remains enabled."
        )
        accepted.pop("graph_store")

    # Let pydantic validate provider-specific config before Memory.from_config
    # opens network/database connections.
    memory_config_cls(**accepted)
    return accepted


def _ensure_mem0_dir() -> None:
    """Keep mem0 telemetry/history files in a writable local temp directory."""
    os.environ.setdefault("MEM0_DIR", os.path.join(tempfile.gettempdir(), "mewi-mem0"))
