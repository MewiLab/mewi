from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent.schemas.perception_schema import PerceptionSummary, ThreatLevel


@dataclass
class SpatialRecord:
    """A place the creature has been."""

    x: float
    y: float
    z: float
    tick: int
    label: str | None = None


@dataclass
class RawMemoryEvent:
    """Authoritative per-turn memory event owned by Python.

    Unity reports the completed previous plan and the current world snapshot.
    Python records that report together with the new domain intent proposals.
    """

    creature_id: str
    tick: int
    request_id: str
    source: str
    event_type: str
    payload: dict[str, Any]

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "request_id": self.request_id,
            "source": self.source,
            "event_type": self.event_type,
            "payload": self.payload,
        }


@dataclass
class AspectMemory:
    """Short-term summary for one aspect of the cat's recent life."""

    aspect: str
    text: str
    tick: int
    salience: float = 0.0
    memory_kind: str = "working"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect,
            "text": self.text,
            "tick": self.tick,
            "salience": self.salience,
            "memory_kind": self.memory_kind,
            "evidence": self.evidence,
        }


@dataclass
class MicroActionEvent:
    """One normalized Unity live micro-action owned by the memory pipeline."""

    creature_id: str
    event_id: str
    correlation_id: str
    request_id: str
    tick: int
    actor_type: str
    actor_id: str
    target_type: str
    target_id: str
    direction: str
    action: str
    behavior_key: str = ""
    motor_action: str = ""
    phase: str = ""
    status: str = ""
    source_event_id: str = ""
    trust_delta: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "creature_id": self.creature_id,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "tick": self.tick,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "direction": self.direction,
            "action": self.action,
            "behavior_key": self.behavior_key,
            "motor_action": self.motor_action,
            "phase": self.phase,
            "status": self.status,
            "source_event_id": self.source_event_id,
            "trust_delta": self.trust_delta,
            "evidence": self.evidence,
        }


@dataclass
class TurnMemoryWrite:
    """What the summarize_memory node wrote this turn."""

    raw_event: RawMemoryEvent
    aspect_memories: list[AspectMemory]
    micro_action_events: list[MicroActionEvent] = field(default_factory=list)

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "raw_event": self.raw_event.to_prompt_context(),
            "aspect_memories": [
                memory.to_prompt_context() for memory in self.aspect_memories
            ],
            "micro_action_events": [
                event.to_prompt_context() for event in self.micro_action_events
            ],
        }


@dataclass
class MemoryRecall:
    """Structured output from a memory query, ready for LLM context."""

    recent_perceptions: list[PerceptionSummary]
    visited_locations: list[dict[str, Any]]
    threat_history: list[ThreatLevel]
    tick_range: tuple[int, int]
    recent_raw_events: list[RawMemoryEvent] = field(default_factory=list)
    recent_micro_actions: list[MicroActionEvent] = field(default_factory=list)
    short_term: dict[str, list[AspectMemory]] = field(default_factory=dict)

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "memory_ticks": self.tick_range,
            "recent_threats": [t.name.lower() for t in self.threat_history],
            "places_visited": len(self.visited_locations),
            "recent_perceptions": [
                p.to_prompt_context() for p in self.recent_perceptions[-3:]
            ],
            "recent_raw_events": [
                event.to_prompt_context() for event in self.recent_raw_events
            ],
            "recent_micro_actions": [
                event.to_prompt_context() for event in self.recent_micro_actions
            ],
            "short_term": {
                aspect: [item.to_prompt_context() for item in items[-3:]]
                for aspect, items in self.short_term.items()
            },
            "short_term_lines": self.short_term_lines(),
        }

    def short_term_lines(self, limit: int = 8) -> list[str]:
        memories: list[AspectMemory] = []
        for items in self.short_term.values():
            memories.extend(items)
        memories.sort(key=lambda item: (item.tick, item.salience), reverse=True)
        return [
            f"{item.aspect}: {item.text}"
            for item in memories[:limit]
            if item.text.strip()
        ]
