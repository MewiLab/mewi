from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Utterance:
    """One thing one cat said (or did expressively) in a room."""

    speaker_id: str
    text: str
    tone: str = "neutral"
    target_id: str = ""
    at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.speaker_id,
            "text": self.text,
            "tone": self.tone,
            "target": self.target_id,
            "at": self.at,
        }


@dataclass
class RelationshipDelta:
    """How a single utterance moves the bond between two cats."""

    pair: tuple[str, str]
    trust: float = 0.0
    affinity: float = 0.0


@dataclass
class ModeratorDecision:
    """Outcome of one social turn.

    A turn may produce nothing (silence is fine), one utterance, and any
    number of relationship deltas. Mood nudges are kept tiny and are
    applied through the slow mind's existing prompt rather than mutating
    Unity-owned health/mood blocks.
    """

    spoke: bool = False
    utterance: Utterance | None = None
    relationship_deltas: list[RelationshipDelta] = field(default_factory=list)
    mood_nudge: dict[str, float] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "spoke": self.spoke,
            "utterance": self.utterance.to_dict() if self.utterance else None,
            "relationship_deltas": [
                {"pair": list(d.pair), "trust": d.trust, "affinity": d.affinity}
                for d in self.relationship_deltas
            ],
            "mood_nudge": dict(self.mood_nudge),
            "note": self.note,
        }


class Moderator(Protocol):
    """Strategy for picking what happens in a SocialRoom turn.

    Signature matches Concordia's GameMaster shape on purpose:
      (room state, world state, driver cat) -> decision
    so we can swap implementations later without changing the graph.
    """

    async def tick(
        self,
        *,
        room: Any,
        driver_id: str,
        world: Any,
        now: float,
    ) -> ModeratorDecision: ...


class DeterministicModerator:
    """Phase-3 moderator. No LLM, pure rules.

    Rule of thumb: each cat gets one quiet "notice" utterance per room.
    Repeat turns inside the same room stay silent until the membership
    changes and a new room key is minted.
    """

    GREETING_TEMPLATES = {
        "first": "{driver} notices {peer} nearby and sniffs the air.",
        "rejoin": "{driver} flicks an ear toward {peer} as they meet again.",
        "group": "{driver} sweeps a glance across the gathered cats.",
    }

    TRUST_DELTA_PER_GREETING = 0.02
    AFFINITY_DELTA_PER_GREETING = 0.03

    async def tick(
        self,
        *,
        room: Any,
        driver_id: str,
        world: Any,
        now: float,
    ) -> ModeratorDecision:
        peers = [cid for cid in room.members if cid != driver_id]
        if not peers:
            return ModeratorDecision(note="no peers")

        already_noticed = any(line.speaker_id == driver_id for line in room.transcript)
        if already_noticed:
            return ModeratorDecision(note="recently spoke")

        template_key = "group" if len(peers) > 1 else (
            "rejoin" if room.turn_count > 0 else "first"
        )
        text = self.GREETING_TEMPLATES[template_key].format(
            driver=_friendly(driver_id),
            peer=", ".join(_friendly(p) for p in peers),
        )
        utterance = Utterance(
            speaker_id=driver_id,
            text=text,
            tone="friendly",
            target_id=peers[0] if len(peers) == 1 else "",
            at=now,
        )

        deltas = [
            RelationshipDelta(
                pair=_pair(driver_id, peer),
                trust=self.TRUST_DELTA_PER_GREETING,
                affinity=self.AFFINITY_DELTA_PER_GREETING,
            )
            for peer in peers
        ]
        return ModeratorDecision(
            spoke=True,
            utterance=utterance,
            relationship_deltas=deltas,
            mood_nudge={"social": 0.05},
            note=template_key,
        )


def _friendly(creature_id: str) -> str:
    if not creature_id:
        return "the cat"
    text = creature_id.replace("cat_", "").replace("_", " ").strip()
    return text or creature_id


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)
