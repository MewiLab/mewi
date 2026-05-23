from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.social.inbox import InboxStore, PendingUtterance
from app.social.moderator import (
    DeterministicModerator,
    Moderator,
    ModeratorDecision,
    Utterance,
)
from app.social.room import RoomRegistry, SocialRoom, room_key_for
from app.social.transcripts import RelationshipState, RelationshipStore, TranscriptStore
from app.world.presence import CatPresence
from app.world.state import WorldState, WorldStateSnapshot


@dataclass
class SocialTurnResult:
    """What the social turn produced for one driver cat this tick.

    `delivered_inbox` is what the *driver* heard from peers since their
    last tick (consumed and cleared). `decision` is what the driver
    themself contributed this turn — may be silent.
    """

    room: SocialRoom | None
    delivered_inbox: list[PendingUtterance]
    decision: ModeratorDecision
    relationships: list[RelationshipState]

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "room": self.room.to_prompt_context() if self.room else None,
            "delivered_inbox": [item.to_prompt_context() for item in self.delivered_inbox],
            "decision": self.decision.to_dict(),
            "relationships": [r.to_dict() for r in self.relationships],
        }

    def dialogue_for_unity(self) -> list[dict[str, Any]]:
        """Flat list of utterances Unity should render this tick.

        Includes both what peers said to this cat since last tick and
        what this cat said this turn (so the driver's own bubble pops).
        """
        out = [item.utterance.to_dict() for item in self.delivered_inbox]
        if self.decision.utterance is not None:
            out.append(self.decision.utterance.to_dict())
        return out


class SocialService:
    """Owns the social-turn lifecycle for one process.

    Construction parameters are intentionally injectable so tests can
    swap the moderator (deterministic vs LLM) without touching the
    graph.
    """

    def __init__(
        self,
        *,
        world: WorldState,
        moderator: Moderator | None = None,
        rooms: RoomRegistry | None = None,
        inbox: InboxStore | None = None,
        relationships: RelationshipStore | None = None,
        transcripts: TranscriptStore | None = None,
    ) -> None:
        self._world = world
        self._moderator = moderator or DeterministicModerator()
        self._rooms = rooms or RoomRegistry()
        self._inbox = inbox or InboxStore()
        self._relationships = relationships or RelationshipStore()
        self._transcripts = transcripts or TranscriptStore()

    # ─── public api ───────────────────────────────────────────────────────

    async def run_turn(
        self,
        creature_id: str,
        *,
        now: float | None = None,
    ) -> SocialTurnResult:
        when = now if now is not None else time.time()
        snapshot = self._world.snapshot(now=when)
        presence = snapshot.cats.get(creature_id)

        delivered = self._inbox.flush(creature_id)

        if presence is None or not presence.zone_id:
            return SocialTurnResult(
                room=None,
                delivered_inbox=delivered,
                decision=ModeratorDecision(note="no presence"),
                relationships=[],
            )

        peers = snapshot.cats_in_zone(presence.zone_id, exclude=creature_id)
        if not peers:
            return SocialTurnResult(
                room=None,
                delivered_inbox=delivered,
                decision=ModeratorDecision(note="alone"),
                relationships=[],
            )

        room = self._open_room(presence, peers, when)
        decision = await self._moderator.tick(
            room=room,
            driver_id=creature_id,
            world=snapshot,
            now=when,
        )

        relationships_changed = self._apply_decision(room, decision, when)

        return SocialTurnResult(
            room=room,
            delivered_inbox=delivered,
            decision=decision,
            relationships=relationships_changed,
        )

    def relationships_for(self, creature_id: str) -> list[RelationshipState]:
        return self._relationships.for_creature(creature_id)

    def transcript_for_room(self, room_key: str) -> list[dict[str, Any]]:
        return self._transcripts.get(room_key)

    # ─── internals ────────────────────────────────────────────────────────

    def _open_room(
        self,
        presence: CatPresence,
        peers: list[CatPresence],
        now: float,
    ) -> SocialRoom:
        members = tuple(sorted([presence.creature_id, *(p.creature_id for p in peers)]))
        key = room_key_for(members)
        return self._rooms.get_or_create(
            key,
            zone_id=presence.zone_id,
            members=members,
            now=now,
        )

    def _apply_decision(
        self,
        room: SocialRoom,
        decision: ModeratorDecision,
        now: float,
    ) -> list[RelationshipState]:
        if not decision.spoke or decision.utterance is None:
            return []

        utterance = decision.utterance
        utterance.at = utterance.at or now
        room.append(utterance)
        self._transcripts.append(room.room_key, utterance.to_dict())
        self._deliver_to_peers(room, utterance)

        return [
            self._relationships.apply(delta)
            for delta in decision.relationship_deltas
        ]

    def _deliver_to_peers(self, room: SocialRoom, utterance: Utterance) -> None:
        for member in room.members:
            if member == utterance.speaker_id:
                continue
            self._inbox.push(
                member,
                PendingUtterance(
                    room_key=room.room_key,
                    zone_id=room.zone_id,
                    utterance=utterance,
                ),
            )
