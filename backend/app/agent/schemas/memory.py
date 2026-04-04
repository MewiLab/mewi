from dataclasses import dataclass
from typing import Any

from app.agent.schemas.perception import (
    PerceptionSummary,
    ThreatLevel
)


@dataclass
class MemoryRecall:
    """Structured output from a memory query — ready for LLM context."""
    recent_perceptions: list[PerceptionSummary]
    visited_locations: list[dict[str, Any]]
    threat_history: list[ThreatLevel]
    tick_range: tuple[int, int]  # (oldest_tick, newest_tick)

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "memory_ticks": self.tick_range,
            "recent_threats": [t.name.lower() for t in self.threat_history],
            "places_visited": len(self.visited_locations),
            "recent_perceptions": [
                p.to_prompt_context() for p in self.recent_perceptions[-3:]
            ],
        }


@dataclass
class SpatialRecord:
    """A place the creature has been."""
    x: float
    y: float
    z: float
    tick: int
    label: str | None = None  # e.g., "near Pond", "on Roof"