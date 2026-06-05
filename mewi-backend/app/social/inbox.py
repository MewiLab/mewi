from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from app.social.moderator import Utterance


@dataclass
class PendingUtterance:
    """Something said to a cat that the cat has not yet 'heard'.

    Utterances are delivered to peers on *their* next tick, not on the
    speaker's tick. This keeps Unity as cadence authority per cat —
    cat B is not woken just because cat A ticked.
    """

    room_key: str
    zone_id: str
    utterance: Utterance

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "room_key": self.room_key,
            "zone_id": self.zone_id,
            **self.utterance.to_dict(),
        }


class InboxStore:
    """Per-creature pending utterance buffer.

    In-process for v1, bounded so a chatty room cannot run a cat out of
    memory. Move to Redis lists when we ship multi-worker.
    """

    def __init__(self, max_per_cat: int = 16) -> None:
        self._max = max_per_cat
        self._inboxes: dict[str, deque[PendingUtterance]] = defaultdict(
            lambda: deque(maxlen=self._max)
        )

    def push(self, creature_id: str, item: PendingUtterance) -> None:
        if not creature_id:
            return
        self._inboxes[creature_id].append(item)

    def flush(self, creature_id: str) -> list[PendingUtterance]:
        if creature_id not in self._inboxes:
            return []
        bucket = self._inboxes[creature_id]
        items = list(bucket)
        bucket.clear()
        return items
