from __future__ import annotations

import logging
from typing import Any, Protocol

from app.agent.memory.memory_manager import MemoryManager
from app.agent.memory.memory_models import TurnMemoryWrite

logger = logging.getLogger(__name__)


class MemoryStore(Protocol):
    def save_turn_memory(self, write: TurnMemoryWrite) -> dict[str, Any]: ...


class MemoryService:
    """Coordinates hot in-process memory with durable cat memory storage."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store

    def record_turn_memory(
        self,
        memory: MemoryManager,
        write: TurnMemoryWrite,
    ) -> dict[str, Any]:
        """Store a turn in hot memory, then persist raw + short-term rows."""
        memory.record_turn_memory(write)

        if self._store is None:
            return {"persisted": False, "reason": "no_store"}

        try:
            result = self._store.save_turn_memory(write)
        except Exception:
            logger.warning(
                "Durable memory write failed creature_id=%s tick=%s",
                write.raw_event.creature_id,
                write.raw_event.tick,
                exc_info=True,
            )
            return {"persisted": False, "reason": "store_error"}

        return {"persisted": True, **result}
