from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CatPresence:
    """Coarse, backend-owned view of where a cat is and what it just did.

    This is *not* a transform replica. It is the minimum the social and
    planning layers need to ask "which cats are in this zone right now,
    and what did each of them just finish doing".
    """

    creature_id: str
    zone_id: str = ""
    active_zone_ids: tuple[str, ...] = ()
    approx_xy: tuple[float, float] | None = None
    last_action: str = ""
    last_action_target: str = ""
    last_action_at: float = 0.0
    mood: dict[str, float] = field(default_factory=dict)
    last_request_id: str = ""
    last_tick: int = 0

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "creature_id": self.creature_id,
            "zone_id": self.zone_id,
            "active_zone_ids": list(self.active_zone_ids),
            "approx_xy": list(self.approx_xy) if self.approx_xy else None,
            "last_action": self.last_action,
            "last_action_target": self.last_action_target,
            "last_action_at": self.last_action_at,
            "mood": dict(self.mood),
            "last_request_id": self.last_request_id,
            "last_tick": self.last_tick,
        }
