"""
social — multi-cat encounters as group-chat sessions.

A SocialRoom is the set of cats co-located in the same zone right now.
The room is the container for one ordered transcript and the
relationship deltas produced by speaking. Rooms tick only when one of
their members ticks (Unity remains the cadence authority per cat).

See: docs/decisions/ADR-011-delayed-social-intent-effects.md
"""

from app.social.bids import SocialBid, SocialBidStore, SocialFeedback
from app.social.inbox import InboxStore, PendingUtterance
from app.social.moderator import (
    DeterministicModerator,
    Moderator,
    ModeratorDecision,
    Utterance,
)
from app.social.room import SocialRoom, room_key_for
from app.social.service import SocialService, SocialTurnResult
from app.social.transcripts import RelationshipStore, TranscriptStore

__all__ = [
    "DeterministicModerator",
    "InboxStore",
    "Moderator",
    "ModeratorDecision",
    "PendingUtterance",
    "RelationshipStore",
    "SocialBid",
    "SocialBidStore",
    "SocialFeedback",
    "SocialRoom",
    "SocialService",
    "SocialTurnResult",
    "TranscriptStore",
    "Utterance",
    "room_key_for",
]
