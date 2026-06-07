from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.social.bids import SocialBidStore, SocialFeedback
from app.social.inbox import InboxStore, PendingUtterance
from app.social.moderator import (
    DeterministicModerator,
    Moderator,
    ModeratorDecision,
    RelationshipDelta,
    Utterance,
)
from app.social.room import RoomRegistry, SocialRoom, room_key_for
from app.social.transcripts import RelationshipState, RelationshipStore, TranscriptStore
from app.world.presence import CatPresence
from app.world.state import WorldState


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
    social_feedback: list[SocialFeedback] | None = None

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "room": self.room.to_prompt_context() if self.room else None,
            "delivered_inbox": [item.to_prompt_context() for item in self.delivered_inbox],
            "decision": self.decision.to_dict(),
            "relationships": [r.to_dict() for r in self.relationships],
            "social_feedback": [
                item.to_dict() for item in (self.social_feedback or [])
            ],
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
        bids: SocialBidStore | None = None,
        relationships: RelationshipStore | None = None,
        transcripts: TranscriptStore | None = None,
    ) -> None:
        self._world = world
        self._moderator = moderator or DeterministicModerator()
        self._rooms = rooms or RoomRegistry()
        self._inbox = inbox or InboxStore()
        self._bids = bids or SocialBidStore()
        self._relationships = relationships or RelationshipStore()
        self._transcripts = transcripts or TranscriptStore()

    # Small positive bumps when a cat speaks to a peer of its own accord.
    AGENT_TRUST_DELTA = 0.02
    AGENT_AFFINITY_DELTA = 0.03
    ACK_AFFINITY_DELTA = 0.01
    IGNORED_AFFINITY_DELTA = -0.01

    # ─── public api ───────────────────────────────────────────────────────

    async def observe_turn(
        self,
        creature_id: str,
        *,
        now: float | None = None,
    ) -> SocialTurnResult:
        """Listen half of a social tick, run before the minds.

        Flushes what peers said to this cat since last tick and opens the
        room so the prompt has social context. It does not author anything
        — the cat's own line is decided by the minds and routed later by
        :meth:`publish_turn`.
        """
        when = now if now is not None else time.time()
        snapshot = self._world.snapshot(now=when)
        presence = snapshot.cats.get(creature_id)

        delivered = self._inbox.flush(creature_id)
        social_feedback = self._bids.flush_feedback(creature_id)
        relationships = self._relationships.for_creature(creature_id)

        if presence is None or not presence.zone_id:
            return SocialTurnResult(
                room=None,
                delivered_inbox=delivered,
                decision=ModeratorDecision(note="no presence"),
                relationships=relationships,
                social_feedback=social_feedback,
            )

        peers = snapshot.cats_in_zone(presence.zone_id, exclude=creature_id)
        if not peers:
            return SocialTurnResult(
                room=None,
                delivered_inbox=delivered,
                decision=ModeratorDecision(note="alone"),
                relationships=relationships,
                social_feedback=social_feedback,
            )

        room = self._open_room(presence, peers, when)
        return SocialTurnResult(
            room=room,
            delivered_inbox=delivered,
            decision=ModeratorDecision(note="listening"),
            relationships=relationships,
            social_feedback=social_feedback,
        )

    async def publish_turn(
        self,
        creature_id: str,
        *,
        say: str = "",
        target: str = "",
        tone: str = "neutral",
        act_kind: str = "message",
        expects_reply: bool = False,
        now: float | None = None,
    ) -> SocialTurnResult:
        """Speak half of a social tick, run after the minds.

        If the cat authored words (``say``), route them to the addressed
        peer — or to everyone in the room when ``target`` is empty. When the
        cat stayed silent, the moderator may emit a low-rate ambient beat
        (it greets a room once and then stays quiet until membership
        changes), so quiet rooms still feel alive without chattering.
        """
        when = now if now is not None else time.time()
        snapshot = self._world.snapshot(now=when)
        presence = snapshot.cats.get(creature_id)

        if presence is None or not presence.zone_id:
            return SocialTurnResult(
                room=None,
                delivered_inbox=[],
                decision=ModeratorDecision(note="no presence"),
                relationships=[],
                social_feedback=[],
            )

        peers = snapshot.cats_in_zone(presence.zone_id, exclude=creature_id)
        if not peers:
            return SocialTurnResult(
                room=None,
                delivered_inbox=[],
                decision=ModeratorDecision(note="alone"),
                relationships=[],
                social_feedback=[],
            )

        room = self._open_room(presence, peers, when)

        words = " ".join(str(say).split()) if say else ""
        if words and self._is_recent_repeat(room, creature_id, words):
            words = ""  # ADR-039 anti-loop: never re-publish our own recent line.
        if words:
            decision = self._author_utterance(
                creature_id,
                room,
                words,
                target,
                tone,
                when,
                act_kind=act_kind,
                expects_reply=expects_reply,
            )
        else:
            decision = await self._moderator.tick(
                room=room,
                driver_id=creature_id,
                world=snapshot,
                now=when,
            )

        relationships_changed = self._apply_decision(room, decision, when)
        return SocialTurnResult(
            room=room,
            delivered_inbox=[],
            decision=decision,
            relationships=relationships_changed,
            social_feedback=[],
        )

    async def run_turn(
        self,
        creature_id: str,
        *,
        now: float | None = None,
    ) -> SocialTurnResult:
        """Listen and speak in one call (moderator-authored fallback only).

        Convenience for callers outside the behavior graph and for tests.
        The graph runs :meth:`observe_turn` and :meth:`publish_turn` on
        either side of the minds so the cat can author its own line.
        """
        when = now if now is not None else time.time()
        observed = await self.observe_turn(creature_id, now=when)
        if observed.room is None:
            return observed
        spoken = await self.publish_turn(creature_id, now=when)
        return SocialTurnResult(
            room=observed.room,
            delivered_inbox=observed.delivered_inbox,
            decision=spoken.decision,
            relationships=spoken.relationships,
            social_feedback=observed.social_feedback,
        )

    def resolve_observed_bids(
        self,
        creature_id: str,
        *,
        delivered_inbox: list[dict[str, Any]],
        selected_intent: str,
        target_id: str = "",
        spoke: bool = False,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Close bids this cat heard once its independent intent is known."""

        when = now if now is not None else time.time()
        intent = _normalize_intent(selected_intent)
        target = _clean_text(target_id)
        outcomes: list[dict[str, Any]] = []

        for item in delivered_inbox:
            if not isinstance(item, dict):
                continue
            bid_id = _clean_text(item.get("bid_id"))
            sender = _clean_text(item.get("from") or item.get("speaker_id"))
            if not bid_id or not sender:
                continue

            outcome, note = _bid_outcome(
                intent=intent,
                target_id=target,
                sender_id=sender,
                responder_id=creature_id,
                spoke=spoke,
            )
            bid = self._bids.close(
                bid_id,
                responder_id=creature_id,
                outcome=outcome,
                note=note,
                now=when,
            )
            if bid is None:
                continue
            relationship = self._apply_bid_relationship(bid.from_id, bid.to_id, outcome)
            payload = bid.to_dict()
            payload["note"] = note
            if relationship is not None:
                payload["relationship"] = relationship.to_dict()
            outcomes.append(payload)

        return outcomes

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

    @staticmethod
    def _resolve_member(target: str, members: tuple[str, ...]) -> str:
        """Map a semantic/affordance target id onto a real room member (ADR-039).

        Unity affordances use ids like ``kosto_cat`` / ``cat_kosto`` while rooms
        key on creature ids like ``kosto``. Resolve aliases so a directed line is
        not silently downgraded to a broadcast.
        """
        if not _clean_text(target):
            return ""
        if target in members:
            return target
        base = _creature_base(target)
        for member in members:
            if member == target or _creature_base(member) == base:
                return member
        return ""

    def _is_recent_repeat(
        self,
        room: SocialRoom,
        speaker_id: str,
        text: str,
        *,
        lookback: int = 3,
    ) -> bool:
        """True if ``text`` matches one of the speaker's last lines (ADR-039)."""
        norm = _clean_text(text).lower()
        if not norm:
            return False
        own_lines = [
            _clean_text(row.get("text")).lower()
            for row in self._transcripts.get(room.room_key)
            if isinstance(row, dict) and _clean_text(row.get("from")) == speaker_id
        ]
        return norm in own_lines[-lookback:]

    def _author_utterance(
        self,
        speaker_id: str,
        room: SocialRoom,
        text: str,
        target: str,
        tone: str,
        now: float,
        *,
        act_kind: str,
        expects_reply: bool,
    ) -> ModeratorDecision:
        """Turn agent-authored words into a routable utterance + bonds."""
        resolved = self._resolve_member(target, room.members)
        recipient = resolved if resolved and resolved != speaker_id else ""
        addressees = (
            [recipient]
            if recipient
            else [m for m in room.members if m != speaker_id]
        )
        utterance = Utterance(
            speaker_id=speaker_id,
            text=text,
            tone=tone or "neutral",
            target_id=recipient,
            at=now,
            act_kind=act_kind or "message",
            expects_reply=bool(expects_reply and recipient),
        )
        if utterance.expects_reply:
            bid = self._bids.create(
                from_id=speaker_id,
                to_id=recipient,
                room_key=room.room_key,
                text=text,
                tone=utterance.tone,
                kind=utterance.act_kind,
                now=now,
            )
            utterance.bid_id = bid.bid_id
        deltas = [
            RelationshipDelta(
                pair=_pair(speaker_id, peer),
                trust=self.AGENT_TRUST_DELTA,
                affinity=self.AGENT_AFFINITY_DELTA,
            )
            for peer in addressees
        ]
        return ModeratorDecision(
            spoke=True,
            utterance=utterance,
            relationship_deltas=deltas,
            mood_nudge={"social": 0.05},
            note="agent_spoke",
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

    def _apply_bid_relationship(
        self,
        from_id: str,
        to_id: str,
        outcome: str,
    ) -> RelationshipState | None:
        if outcome == "ignored":
            return self._relationships.apply(
                RelationshipDelta(
                    pair=_pair(from_id, to_id),
                    affinity=self.IGNORED_AFFINITY_DELTA,
                )
            )
        if outcome == "acknowledged":
            return self._relationships.apply(
                RelationshipDelta(
                    pair=_pair(from_id, to_id),
                    affinity=self.ACK_AFFINITY_DELTA,
                )
            )
        return None

    def _deliver_to_peers(self, room: SocialRoom, utterance: Utterance) -> None:
        # A targeted line reaches only the addressed cat (still gated by
        # room membership); an untargeted line is heard by the whole room.
        targeted = (
            utterance.target_id
            and utterance.target_id != utterance.speaker_id
            and utterance.target_id in room.members
        )
        for member in room.members:
            if member == utterance.speaker_id:
                continue
            if targeted and member != utterance.target_id:
                continue
            self._inbox.push(
                member,
                PendingUtterance(
                    room_key=room.room_key,
                    zone_id=room.zone_id,
                    utterance=utterance,
                ),
            )


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _creature_base(value: Any) -> str:
    """Strip cat/kitten affixes so ``kosto_cat``/``cat_kosto``/``kosto`` align."""
    text = _clean_text(value).lower()
    for affix in ("_cat", "cat_", "_kitten", "kitten_"):
        if text.startswith(affix):
            text = text[len(affix):]
        if text.endswith(affix):
            text = text[: -len(affix)]
    return text


def _bid_outcome(
    *,
    intent: str,
    target_id: str,
    sender_id: str,
    responder_id: str,
    spoke: bool,
) -> tuple[str, str]:
    if intent == "SOCIALIZE" and _creature_base(target_id) == _creature_base(sender_id):
        if spoke:
            return "replied", f"{responder_id} replied to the social bid."
        return "acknowledged", f"{responder_id} acknowledged the social bid with body language."
    if intent == "SAFETY":
        return "deferred", "The receiver was focused on safety, so the bid was deferred."
    return "ignored", "The receiver did not answer this social bid."


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _normalize_intent(value: Any) -> str:
    text = _clean_text(value).upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "SOCIAL": "SOCIALIZE",
        "SAFE": "SAFETY",
        "FEAR": "SAFETY",
        "FLEE": "SAFETY",
    }
    return aliases.get(text, text or "IDLE")
