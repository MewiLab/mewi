import logging
from collections import deque
from typing import Any

from app.agent.memory.models import (
    AspectMemory,
    MemoryRecall,
    RawMemoryEvent,
    SpatialRecord,
    TurnMemoryWrite,
)
from app.agent.schemas.perception_schema import PerceptionSummary

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Maintains bounded in-process memory for one creature runtime.

    Storage structures:
      - perception_history: ring buffer of recent PerceptionSummary objects.
      - spatial_log: ring buffer of SpatialRecord entries.
      - raw_events: authoritative Python-owned turn records.
      - short_term: aspect summaries derived from raw events.

    All are bounded so memory does not grow unbounded during long sessions.
    """

    def __init__(
        self,
        max_ticks: int = 50,
        spatial_resolution: float = 2.0,
    ):
        # Configuration
        self.max_ticks = max_ticks
        self.spatial_resolution = spatial_resolution  # min distance between logged positions

        # Storage
        self._perception_history: deque[PerceptionSummary] = deque(maxlen=max_ticks)
        self._spatial_log: deque[SpatialRecord] = deque(maxlen=max_ticks * 2)
        self._raw_events: deque[RawMemoryEvent] = deque(maxlen=max_ticks * 2)
        self._short_term: dict[str, deque[AspectMemory]] = {}

    # ─── Write API ───────────────────────────────────────────────────────

    def record(self, summary: PerceptionSummary) -> None:
        """
        Store a perception tick.  Called by the agent after each
        successful SnapshotManager.process() call.

        Also logs the creature's position to spatial memory if it has
        moved far enough from the last recorded position.
        """
        self._perception_history.append(summary)
        self._maybe_log_position(summary)
        logger.debug(
            "Memory recorded tick %d (buffer: %d/%d)",
            summary.tick,
            len(self._perception_history),
            self.max_ticks,
        )

    def annotate_location(self, label: str, summary: PerceptionSummary) -> None:
        """
        Explicitly label the current location — e.g., when the agent
        discovers a landmark.  "I found the Pond here."
        """
        pos = getattr(summary.creature, "position", None)
        if pos is None:
            return
        self._spatial_log.append(
            SpatialRecord(x=pos.x, y=pos.y, z=pos.z, tick=summary.tick, label=label)
        )

    def record_turn_memory(self, write: TurnMemoryWrite) -> None:
        """Store an authoritative raw turn event and its short-term summaries."""
        self.record_raw_event(write.raw_event)
        for memory in write.aspect_memories:
            self.record_short_term(memory)

    def record_raw_event(self, event: RawMemoryEvent) -> None:
        self._raw_events.append(event)

    def record_short_term(self, memory: AspectMemory) -> None:
        aspect = memory.aspect.strip().lower() or "general"
        bucket = self._short_term.setdefault(
            aspect,
            deque(maxlen=max(3, self.max_ticks // 2)),
        )
        bucket.append(memory)

    def clear(self) -> None:
        """Reset all memory.  Useful between episodes or tests."""
        self._perception_history.clear()
        self._spatial_log.clear()
        self._raw_events.clear()
        self._short_term.clear()

    # ─── Read API ────────────────────────────────────────────────────────

    def recall(self, last_n: int | None = None) -> MemoryRecall:
        """
        Retrieve recent memory as a structured object.

        Args:
            last_n: How many recent ticks to include.  None = all stored.

        Returns a MemoryRecall that the LLM can consume via
        .to_prompt_context().
        """
        history = list(self._perception_history)
        if last_n is not None:
            history = history[-last_n:]

        tick_range = (
            (history[0].tick, history[-1].tick) if history else (0, 0)
        )

        return MemoryRecall(
            recent_perceptions=history,
            visited_locations=[
                {"x": r.x, "y": r.y, "z": r.z, "label": r.label, "tick": r.tick}
                for r in self._spatial_log
            ],
            threat_history=[p.threat_level for p in history],
            tick_range=tick_range,
            recent_raw_events=list(self._raw_events)[-(last_n or 5):],
            short_term={
                aspect: list(items)[-(last_n or 5):]
                for aspect, items in self._short_term.items()
            },
        )

    def has_visited_near(self, x: float, z: float, radius: float = 5.0) -> bool:
        """Check if the creature has been near a given xz position."""
        for record in self._spatial_log:
            dist_sq = (record.x - x) ** 2 + (record.z - z) ** 2
            if dist_sq <= radius ** 2:
                return True
        return False

    def last_seen_entity(self, entity_name: str) -> dict[str, Any] | None:
        """
        Search backward through perception history for the most recent
        sighting of a named entity.  Returns its position and tick, or
        None if never seen.
        """
        for summary in reversed(self._perception_history):
            for entity in summary.nearby_entities:
                name = getattr(entity, "name", "")
                if entity_name.lower() in name.lower():
                    pos = getattr(entity, "position", None)
                    if pos is not None:
                        return {
                            "name": name,
                            "x": pos.x,
                            "y": pos.y,
                            "z": pos.z,
                            "tick": summary.tick,
                            "ticks_ago": self._current_tick() - summary.tick,
                        }
        return None

    @property
    def tick_count(self) -> int:
        return len(self._perception_history)

    @property
    def raw_event_count(self) -> int:
        return len(self._raw_events)

    @property
    def short_term_count(self) -> int:
        return sum(len(items) for items in self._short_term.values())

    # ─── Internal ────────────────────────────────────────────────────────

    def _maybe_log_position(self, summary: PerceptionSummary) -> None:
        """Log position only if creature moved beyond spatial_resolution."""
        pos = getattr(summary.creature, "position", None)
        if pos is None:
            return

        if self._spatial_log:
            last = self._spatial_log[-1]
            dist_sq = (pos.x - last.x) ** 2 + (pos.z - last.z) ** 2
            if dist_sq < self.spatial_resolution ** 2:
                return  # Hasn't moved enough, skip.

        self._spatial_log.append(
            SpatialRecord(x=pos.x, y=pos.y, z=pos.z, tick=summary.tick)
        )

    def _current_tick(self) -> int:
        if self._perception_history:
            return self._perception_history[-1].tick
        return 0
