"""The single abstraction for durable memory.

Hot, per-tick state lives in :class:`~app.agent.memory.memory_manager.MemoryManager`.
Anything that must survive a restart or support cross-session / semantic /
graph recall goes through a ``MemoryStore``.

This is intentionally a tiny Protocol so the agent package stays decoupled
from infrastructure: concrete implementations (Supabase, mem0/Neo4j) live in
``app/repositories`` and are injected at startup.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.agent.memory.memory_models import TurnMemoryWrite


@runtime_checkable
class MemoryStore(Protocol):
    """Durable memory backend the MemoryManager delegates to."""

    async def record_turn(self, write: TurnMemoryWrite) -> None:
        """Persist one planning turn (raw event + aspect memories)."""
        ...

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return memories relevant to ``query`` for one creature."""
        ...
