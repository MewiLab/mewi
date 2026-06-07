import asyncio
import logging
from collections import deque
from typing import TYPE_CHECKING, Any

from app.agent.memory.memory_models import (
    AspectMemory,
    MemoryRecall,
    MicroActionEvent,
    RawMemoryEvent,
    SpatialRecord,
    TurnMemoryWrite,
)
from app.agent.schemas.perception_schema import PerceptionSummary

if TYPE_CHECKING:
    from app.agent.memory.memory_store import MemoryStore

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

    Consolidation is the manager's own tool: :meth:`consolidate` folds
    overflowing short-term buckets into a single recap, delegating the actual
    summarization to ``memory_consolidate.consolidate_aspect_llm``.
    """

    def __init__(
        self,
        max_ticks: int = 50,
        spatial_resolution: float = 2.0,
        *,
        store: "MemoryStore | None" = None,
    ):
        # Configuration
        self.max_ticks = max_ticks
        self.spatial_resolution = spatial_resolution  # min distance between logged positions
        self._store = store  # durable backend (Supabase / mem0); None = hot-only

        # Storage
        self._perception_history: deque[PerceptionSummary] = deque(maxlen=max_ticks)
        self._spatial_log: deque[SpatialRecord] = deque(maxlen=max_ticks * 2)
        self._raw_events: deque[RawMemoryEvent] = deque(maxlen=max_ticks * 2)
        self._micro_action_events: deque[MicroActionEvent] = deque(maxlen=max_ticks * 4)
        self._short_term: dict[str, deque[AspectMemory]] = {}

        # Consolidation bookkeeping
        self._consolidating: set[str] = set()
        self._consolidation_tasks: set[asyncio.Task] = set()
        # Monotonic count of raw turns ever recorded. The cadence gate compares
        # against this rather than len(self._raw_events): the latter is a bounded
        # deque that pins at maxlen, which would freeze the gate at 0 and stop
        # consolidation forever once the buffer saturates.
        self._raw_event_total = 0
        self._last_consolidated_raw_count = 0

        # Background durable-write tasks (kept referenced so they aren't GC'd)
        self._store_tasks: set[asyncio.Task] = set()

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
        for event in write.micro_action_events:
            self.record_micro_action_event(event)
        for memory in write.aspect_memories:
            self.record_short_term(memory)

    def record_raw_event(self, event: RawMemoryEvent) -> None:
        self._raw_events.append(event)
        self._raw_event_total += 1

    def record_micro_action_event(self, event: MicroActionEvent) -> None:
        self._micro_action_events.append(event)

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
        self._micro_action_events.clear()
        self._short_term.clear()
        self._consolidating.clear()
        self._raw_event_total = 0
        self._last_consolidated_raw_count = 0

    # ─── Short-term consolidation ─────────────────────────────────────────

    def schedule_consolidation(
        self,
        llm,
        *,
        threshold: int = 6,
        keep_recent: int = 2,
        min_turns: int = 10,
        related_memories: list[dict[str, Any]] | None = None,
    ) -> None:
        """Run :meth:`consolidate` in the background; never blocks the tick."""
        if llm is None:
            return
        if self._consolidation_tasks:
            return
        if not self._has_consolidation_work(
            threshold=threshold,
            keep_recent=keep_recent,
            min_turns=min_turns,
        ):
            return
        task = asyncio.create_task(
            self._run_consolidation(
                llm,
                threshold=threshold,
                keep_recent=keep_recent,
                min_turns=min_turns,
                related_memories=list(related_memories or []),
            )
        )
        self._consolidation_tasks.add(task)
        task.add_done_callback(self._consolidation_tasks.discard)

    async def _run_consolidation(
        self,
        llm,
        *,
        threshold: int,
        keep_recent: int,
        min_turns: int,
        related_memories: list[dict[str, Any]],
    ) -> None:
        try:
            await self.consolidate(
                llm,
                threshold=threshold,
                keep_recent=keep_recent,
                min_turns=min_turns,
                related_memories=related_memories,
            )
        except Exception:
            logger.warning("STM consolidation failed", exc_info=True)

    async def consolidate(
        self,
        llm,
        *,
        threshold: int = 6,
        keep_recent: int = 2,
        min_turns: int = 10,
        related_memories: list[dict[str, Any]] | None = None,
    ) -> int:
        """Fold current Python-side short-term memory into one reflective recap.

        Keeps the ``keep_recent`` newest entries per aspect verbatim and
        replaces the older short-term notes with one LLM reflection. The write-back is
        synchronous (so it is atomic relative to other coroutines on the loop),
        and entries appended while the LLM call awaits are preserved. ``min_turns``
        uses backend raw-turn count, so this cadence has no Unity payload dependency.
        """
        if llm is None:
            return 0
        # Local import keeps the consolidate tool out of the package import
        # cycle (memory_consolidate -> creature_runtime -> app.agent.memory).
        from app.agent.memory.memory_consolidate import consolidate_memory_llm

        if not self._has_consolidation_work(
            threshold=threshold,
            keep_recent=keep_recent,
            min_turns=min_turns,
        ):
            return 0
        prompt_memories, originals = self._consolidation_memories(keep_recent=keep_recent)
        if not prompt_memories or not originals:
            return 0

        self._consolidating.add("memory")
        try:
            recap = await consolidate_memory_llm(
                llm,
                prompt_memories,
                related_memories=related_memories or [],
            )
            if not recap:
                return 0
            ticks = [memory.tick for memory in originals]
            summary = AspectMemory(
                aspect="reflection",
                text=recap,
                tick=max(ticks, default=0),
                salience=max((m.salience for m in originals), default=0.3),
                memory_kind="summary",
                evidence={
                    "consolidated_from": len(originals),
                    "source_count": len(prompt_memories),
                    "related_count": len(related_memories or []),
                    "tick_start": min(ticks, default=0),
                    "tick_end": max(ticks, default=0),
                    "summary_style": "reflective",
                },
            )
            self._replace_consolidated_short_term(originals, summary)
            await self._persist_summaries([summary])
            self._last_consolidated_raw_count = self._raw_event_total
            return 1
        finally:
            self._consolidating.discard("memory")

    def _has_consolidation_work(
        self,
        *,
        threshold: int,
        keep_recent: int,
        min_turns: int,
    ) -> bool:
        if "memory" in self._consolidating:
            return False
        if min_turns > 0 and self._raw_event_total - self._last_consolidated_raw_count < min_turns:
            return False
        prompt_memories, originals = self._consolidation_memories(keep_recent=keep_recent)
        return len(prompt_memories) > threshold and len(originals) >= 2

    def _consolidation_memories(
        self,
        *,
        keep_recent: int,
    ) -> tuple[list[AspectMemory], list[AspectMemory]]:
        prompt_memories: list[AspectMemory] = []
        originals: list[AspectMemory] = []
        for items in self._short_term.values():
            memories = [
                memory for memory in items
                if memory.memory_kind != "summary" and memory.text.strip()
            ]
            prompt_memories.extend(memories)
            originals.extend(memories[:-keep_recent] if keep_recent > 0 else memories)
        prompt_memories.sort(key=lambda memory: (memory.tick, memory.aspect))
        originals.sort(key=lambda memory: (memory.tick, memory.aspect))
        return prompt_memories, originals

    def _replace_consolidated_short_term(
        self,
        originals: list[AspectMemory],
        summary: AspectMemory,
    ) -> None:
        folded = {id(memory) for memory in originals}
        for bucket in self._short_term.values():
            remaining = [memory for memory in bucket if id(memory) not in folded]
            bucket.clear()
            bucket.extend(remaining)
        self.record_short_term(summary)

    def _replace_short_term(
        self,
        aspect: str,
        originals: list[AspectMemory],
        summary: AspectMemory,
    ) -> None:
        """Swap the `originals` for a single `summary` at the front of the
        bucket, preserving (in order) any entries appended meanwhile.
        """
        bucket = self._short_term.get(aspect)
        if bucket is None:
            return
        folded = {id(memory) for memory in originals}
        remaining = [memory for memory in bucket if id(memory) not in folded]
        bucket.clear()
        bucket.append(summary)
        bucket.extend(remaining)

    # ─── Durable store (the manager's one persistence tool) ───────────────

    def persist_turn(self, write: TurnMemoryWrite) -> None:
        """Record the turn in hot memory now; persist to the durable store in
        the background so the tick never waits on Supabase / mem0 extraction.

        This is the single write seam: the behavior graph calls it once per
        tick. With no store attached it is just the in-process write.
        """
        self.record_turn_memory(write)
        if self._store is None:
            return
        try:
            task = asyncio.create_task(self._safe_store_write(write))
        except RuntimeError:
            logger.warning("Durable memory write skipped: no running event loop")
            return
        self._store_tasks.add(task)
        task.add_done_callback(self._store_tasks.discard)

    async def _safe_store_write(self, write: TurnMemoryWrite) -> None:
        try:
            await self._store.record_turn(write)
        except Exception:
            logger.warning("Durable memory write failed", exc_info=True)

    async def _persist_summaries(self, summaries: list[AspectMemory]) -> None:
        if self._store is None or not summaries:
            return
        last = self._raw_events[-1] if self._raw_events else None
        creature_id = last.creature_id if last is not None else ""
        request_id = last.request_id if last is not None else ""
        tick = max((summary.tick for summary in summaries), default=0)
        raw_event = RawMemoryEvent(
            creature_id=creature_id,
            tick=tick,
            request_id=request_id,
            source="python",
            event_type="memory_consolidation",
            payload={
                "summary_count": len(summaries),
                "aspects": [summary.aspect for summary in summaries],
            },
        )
        await self._safe_store_write(
            TurnMemoryWrite(raw_event=raw_event, aspect_memories=summaries)
        )

    async def recall_longterm(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
        now_tick: int | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic/keyword/graph recall via the durable store, if attached."""
        if self._store is None:
            return []
        return await self._store.search(
            query,
            creature_id=creature_id,
            limit=limit,
            now_tick=now_tick,
        )

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
            # Keep a wider raw-event window than `last_n`: it isn't rendered in
            # the prompt, but need assessment reads intents from it
            # and needs more than a couple of ticks to detect neglect.
            recent_raw_events=list(self._raw_events)[-max(last_n or 5, 10):],
            recent_micro_actions=list(self._micro_action_events)[-max(last_n or 5, 10):],
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

    @property
    def micro_action_event_count(self) -> int:
        return len(self._micro_action_events)

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
