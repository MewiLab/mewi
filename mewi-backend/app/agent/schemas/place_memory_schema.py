from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass(frozen=True)
class PlaceMemoryEntry:
    """Per-creature memory for one semantic zone."""

    zone_id: str
    visit_count: int = 0
    last_visited_at: float = 0.0
    last_seen_at: float = 0.0
    familiarity: float = 0.0
    last_arrival_request_id: str = ""
    summary: str = ""
    summary_updated_at: float = 0.0
    summary_evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlaceMemoryEntry":
        last_seen_at = float(
            data.get("last_seen_at")
            or data.get("last_observed_at")
            or data.get("last_visited_at")
            or 0.0
        )
        return cls(
            zone_id=str(data.get("zone_id") or ""),
            visit_count=max(0, int(data.get("visit_count") or 0)),
            last_visited_at=float(data.get("last_visited_at") or 0.0),
            last_seen_at=last_seen_at,
            familiarity=max(0.0, min(1.0, float(data.get("familiarity") or 0.0))),
            last_arrival_request_id=str(data.get("last_arrival_request_id") or ""),
            summary=str(data.get("summary") or ""),
            summary_updated_at=float(data.get("summary_updated_at") or 0.0),
            summary_evidence=(
                data.get("summary_evidence")
                if isinstance(data.get("summary_evidence"), dict)
                else {}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "visit_count": self.visit_count,
            "last_visited_at": self.last_visited_at,
            "last_seen_at": self.last_seen_at,
            "familiarity": self.familiarity,
            "last_arrival_request_id": self.last_arrival_request_id,
            "summary": self.summary,
            "summary_updated_at": self.summary_updated_at,
            "summary_evidence": self.summary_evidence,
        }


@dataclass(frozen=True)
class PlaceMemoryOverlay:
    """Hot per-creature place memory loaded from Redis."""

    entries: dict[str, PlaceMemoryEntry] = field(default_factory=dict)

    def get(self, zone_id: str) -> PlaceMemoryEntry | None:
        return self.entries.get(zone_id)

    def recent(self, limit: int = 4) -> list[PlaceMemoryEntry]:
        return sorted(
            self.entries.values(),
            key=lambda entry: max(entry.last_seen_at, entry.last_visited_at),
            reverse=True,
        )[:limit]


class PlaceMemoryContextDict(TypedDict):
    """Wire shape of the place-memory context shared across graph nodes.

    Kept as a TypedDict (not a dataclass) so it survives the existing dict-based
    graph state without coercion. Callers that read these keys should import
    this type to make the contract explicit.
    """

    current_zone_id: str
    active_zone_ids: list[str]
    reachable_zone_ids: list[str]
    known_zone_ids: list[str]
    best_exploration_target: str
    lines: list[str]


@dataclass(frozen=True)
class PlaceMemoryContext:
    """Small, prompt-safe context produced by place memory reflection."""

    current_zone_id: str = ""
    active_zone_ids: tuple[str, ...] = ()
    reachable_zone_ids: tuple[str, ...] = ()
    known_zone_ids: tuple[str, ...] = ()
    best_exploration_target: str = ""
    lines: tuple[str, ...] = ()

    def to_prompt_context(self) -> PlaceMemoryContextDict:
        return {
            "current_zone_id": self.current_zone_id,
            "active_zone_ids": list(self.active_zone_ids),
            "reachable_zone_ids": list(self.reachable_zone_ids),
            "known_zone_ids": list(self.known_zone_ids),
            "best_exploration_target": self.best_exploration_target,
            "lines": list(self.lines),
        }
