"""
world — backend-owned coarse world model.

This module is the single Python-side place that knows where each cat
currently *is* at zone resolution, what each cat just did, and which
cats are close enough to interact.

It deliberately mirrors only what the social and planning layers need:
zones, approximate position, the last action the backend asked Unity to
play, and a small recent-event log. It is not a physics replica of the
Unity scene — geometry, navigation, and animation still live in Unity.

See: docs/decisions/ADR-010-backend-owned-world-and-social-chat.md
"""

from app.world.presence import CatPresence
from app.world.state import WorldState, WorldStateSnapshot

__all__ = [
    "CatPresence",
    "WorldState",
    "WorldStateSnapshot",
]
