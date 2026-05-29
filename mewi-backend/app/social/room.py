from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.social.moderator import Utterance


def room_key_for(creature_ids: list[str] | tuple[str, ...]) -> str:
    """Stable room id for a set of co-located cats.

    Same set → same key, regardless of who triggered the lookup.
    Different set → different key, so leaving/joining mints a new room.
    """
    cleaned = sorted({cid.strip() for cid in creature_ids if cid and cid.strip()})
    return ",".join(cleaned)


@dataclass
class SocialRoom:
    """A live group-chat between cats co-located in the same zone."""

    room_key: str
    zone_id: str
    members: tuple[str, ...]
    transcript: list[Utterance] = field(default_factory=list)
    opened_at: float = 0.0
    last_turn_at: float = 0.0
    turn_count: int = 0

    def append(self, utterance: Utterance) -> None:
        self.transcript.append(utterance)
        self.last_turn_at = max(self.last_turn_at, utterance.at)
        self.turn_count += 1

    def recent(self, limit: int = 6) -> list[Utterance]:
        if limit <= 0:
            return []
        return self.transcript[-limit:]

    def to_prompt_context(self, limit: int = 6) -> dict[str, Any]:
        return {
            "room_key": self.room_key,
            "zone_id": self.zone_id,
            "members": list(self.members),
            "turn_count": self.turn_count,
            "recent_transcript": [u.to_dict() for u in self.recent(limit=limit)],
        }


class RoomRegistry:
    """Process-global lookup of live rooms by room_key.

    Rooms are created lazily on first co-location. The stable key is the
    member set, so the same cats reuse their transcript if they meet again.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, SocialRoom] = {}

    def get_or_create(
        self,
        room_key: str,
        *,
        zone_id: str,
        members: tuple[str, ...],
        now: float,
    ) -> SocialRoom:
        room = self._rooms.get(room_key)
        if room is None:
            room = SocialRoom(
                room_key=room_key,
                zone_id=zone_id,
                members=members,
                opened_at=now,
                last_turn_at=now,
            )
            self._rooms[room_key] = room
        else:
            room.zone_id = zone_id
            room.members = members
        return room
