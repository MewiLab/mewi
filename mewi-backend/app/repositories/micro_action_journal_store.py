"""Structural journal store for ADR-034 live micro-actions."""
from __future__ import annotations

from typing import Any

from app.agent.memory.memory_models import TurnMemoryWrite
from app.cat_journal.raw_agent_graph import RawCatJournal


class MicroActionJournalStore:
    """Append normalized micro-action events to the existing cat journal."""

    def __init__(self, journal: RawCatJournal):
        self._journal = journal

    async def record_turn(self, write: TurnMemoryWrite) -> None:
        if not write.micro_action_events:
            return
        await self._journal.append_micro_action_events(
            creature_id=write.raw_event.creature_id,
            events=write.micro_action_events,
        )

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
        now_tick: int | None = None,
    ) -> list[dict[str, Any]]:
        return []
