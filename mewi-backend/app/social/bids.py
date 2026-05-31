from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class SocialBid:
    bid_id: str
    from_id: str
    to_id: str
    room_key: str
    text: str
    tone: str
    kind: str
    created_at: float
    status: str = "pending"
    closed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid_id": self.bid_id,
            "from": self.from_id,
            "to": self.to_id,
            "room_key": self.room_key,
            "text": self.text,
            "tone": self.tone,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
        }


@dataclass
class SocialFeedback:
    bid_id: str
    from_id: str
    to_id: str
    outcome: str
    note: str
    at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid_id": self.bid_id,
            "from": self.from_id,
            "to": self.to_id,
            "outcome": self.outcome,
            "note": self.note,
            "at": self.at,
        }


class SocialBidStore:
    """Tracks pending social bids and delayed sender feedback."""

    def __init__(self) -> None:
        self._next_id = 1
        self._bids: dict[str, SocialBid] = {}
        self._feedback: dict[str, list[SocialFeedback]] = defaultdict(list)

    def create(
        self,
        *,
        from_id: str,
        to_id: str,
        room_key: str,
        text: str,
        tone: str,
        kind: str,
        now: float,
    ) -> SocialBid:
        bid = SocialBid(
            bid_id=self._new_id(),
            from_id=from_id,
            to_id=to_id,
            room_key=room_key,
            text=text,
            tone=tone,
            kind=kind,
            created_at=now,
        )
        self._bids[bid.bid_id] = bid
        return bid

    def close(
        self,
        bid_id: str,
        *,
        responder_id: str,
        outcome: str,
        note: str,
        now: float,
    ) -> SocialBid | None:
        bid = self._bids.get(bid_id)
        if bid is None or bid.status != "pending" or bid.to_id != responder_id:
            return None

        bid.status = outcome
        bid.closed_at = now
        self._feedback[bid.from_id].append(
            SocialFeedback(
                bid_id=bid.bid_id,
                from_id=bid.to_id,
                to_id=bid.from_id,
                outcome=outcome,
                note=note,
                at=now,
            )
        )
        return bid

    def flush_feedback(self, creature_id: str) -> list[SocialFeedback]:
        if creature_id not in self._feedback:
            return []
        out = list(self._feedback[creature_id])
        self._feedback[creature_id].clear()
        return out

    def _new_id(self) -> str:
        bid_id = f"bid_{self._next_id:06d}"
        self._next_id += 1
        return bid_id
