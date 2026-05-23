from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.social.moderator import RelationshipDelta


@dataclass
class RelationshipState:
    """Bond between two cats, lexicographically ordered key."""

    pair: tuple[str, str]
    trust: float = 0.0
    affinity: float = 0.0
    encounters: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair": list(self.pair),
            "trust": self.trust,
            "affinity": self.affinity,
            "encounters": self.encounters,
        }


class RelationshipStore:
    """In-process bond state. Promote to Supabase once stable."""

    TRUST_CLAMP = (-1.0, 1.0)
    AFFINITY_CLAMP = (-1.0, 1.0)

    def __init__(self) -> None:
        self._pairs: dict[tuple[str, str], RelationshipState] = {}

    def apply(self, delta: RelationshipDelta) -> RelationshipState:
        key = _normalize_pair(delta.pair)
        state = self._pairs.get(key) or RelationshipState(pair=key)
        state.trust = _clamp(state.trust + delta.trust, *self.TRUST_CLAMP)
        state.affinity = _clamp(state.affinity + delta.affinity, *self.AFFINITY_CLAMP)
        state.encounters += 1
        self._pairs[key] = state
        return state

    def for_creature(self, creature_id: str) -> list[RelationshipState]:
        return [state for key, state in self._pairs.items() if creature_id in key]


class TranscriptStore:
    """Archive of room transcripts past and present, keyed by room_key.

    The live transcript is also held by the SocialRoom itself; this
    store gives the memory summarizer a stable place to read room
    history once a room dissolves.
    """

    def __init__(self) -> None:
        self._lines: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def append(self, room_key: str, utterance_dict: dict[str, Any]) -> None:
        if not room_key:
            return
        self._lines[room_key].append(utterance_dict)

    def get(self, room_key: str) -> list[dict[str, Any]]:
        return list(self._lines.get(room_key, ()))


def _normalize_pair(pair: tuple[str, str]) -> tuple[str, str]:
    a, b = pair
    return (a, b) if a <= b else (b, a)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
