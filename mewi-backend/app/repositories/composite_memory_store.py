"""Fan-out :class:`~app.agent.memory.memory_store.MemoryStore`.

Writes go to every backing store; reads merge their results. A failure in one
store is logged but never breaks the others — durability is best-effort per
store, and a tick must not fail because one backend is down.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent.memory.memory_models import TurnMemoryWrite
from app.agent.memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)


class CompositeMemoryStore:
    """Combine several MemoryStores behind the single MemoryStore interface."""

    def __init__(self, *stores: MemoryStore | None):
        self._stores: list[MemoryStore] = [s for s in stores if s is not None]

    def __bool__(self) -> bool:
        return bool(self._stores)

    async def record_turn(self, write: TurnMemoryWrite) -> None:
        results = await asyncio.gather(
            *(store.record_turn(write) for store in self._stores),
            return_exceptions=True,
        )
        for store, result in zip(self._stores, results):
            if isinstance(result, Exception):
                logger.warning(
                    "MemoryStore %s.record_turn failed: %s",
                    type(store).__name__,
                    result,
                )

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        results = await asyncio.gather(
            *(
                store.search(query, creature_id=creature_id, limit=limit)
                for store in self._stores
            ),
            return_exceptions=True,
        )
        merged: list[dict[str, Any]] = []
        for store, result in zip(self._stores, results):
            if isinstance(result, Exception):
                logger.warning(
                    "MemoryStore %s.search failed: %s", type(store).__name__, result
                )
                continue
            merged.extend(result)
        return merged
