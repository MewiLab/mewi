from __future__ import annotations

from typing import Any

from app.agent.arbitration.helpers.domain_prompt import (
    build_domain_message,
    format_domain_context,
    parse_domain_intent,
)
from app.agent.mind.intents import INTENT_IDLE, INTENT_INVESTIGATE, INTENT_SEEK_PLAYER, INTENT_SOCIALIZE
from app.agent.prompts.sections import clean_text


SOCIAL_PROPOSAL_PROMPT = """
# ROLE: MEW Social Proposal
You inspect nearby peers, relationship memory, and recent social exchange only.

# JOB
Return exactly one intent proposal for the social domain.
Choose SOCIALIZE for a viable nearby peer, SEEK_PLAYER for a human-seeking pull,
INVESTIGATE for a social cue that should be inspected first, or IDLE when social
context should not pull the cat now.
Use PERSONA to shape mood/style and sociability, but do not invent peers,
utterances, or targets. Use PROCESSED SNAPSHOT CONTEXT for current presence and
MEMORY STATE for relationship history and recent exchange.
When SOCIALIZE should include a visible chirp, invitation, or reply, include a
small social_act. social_act is the speaker's intention only; never decide how
the target reacts.

# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
{
  "intent": "<SOCIALIZE | SEEK_PLAYER | INVESTIGATE | IDLE>",
  "target_id": null,
  "mood": "brief embodied mood",
  "style": "short physical style hint",
  "social_act": {
    "kind": "greeting | invite | reply | check_in | message",
    "say": "short cat-like utterance, or empty string for body language only",
    "tone": "brief tone",
    "expects_reply": true
  },
  "reasoning": "one sentence explaining the social pull"
}
"""


def social_proposal_lines(
    world_view: dict[str, Any] | None,
    social_context: dict[str, Any] | None,
) -> list[str]:
    """Return compact SOCIALIZE hints when peers or room context exist."""

    peers = _peer_ids(world_view)
    if not peers:
        room = social_context.get("room") if isinstance(social_context, dict) else None
        members = room.get("members") if isinstance(room, dict) else None
        if isinstance(members, list):
            peers = [clean_text(item) for item in members if clean_text(item)]

    if not peers:
        return []

    lines = [f"Social proposal: SOCIALIZE is viable with nearby peer {peers[0]}."]
    if len(peers) > 1:
        lines.append(f"Social proposal: Other nearby peers include {', '.join(peers[1:4])}.")
    return lines


async def propose_social_intent(llm: Any, state: dict[str, Any]) -> dict[str, Any]:
    prompt = SOCIAL_PROPOSAL_PROMPT + format_domain_context(
        state,
        heading="Social domain: nearby peers, player pull, room context, relationship memory.",
        focus_lines=social_proposal_lines(state.get("world_view"), state.get("social_context")),
    )
    message = build_domain_message(prompt)
    response = await llm.ainvoke([message])
    proposal = parse_domain_intent(
        str(response.content),
        domain="social",
        affordances=state.get("intent_affordances"),
        allowed_intents={INTENT_SOCIALIZE, INTENT_SEEK_PLAYER, INTENT_INVESTIGATE, INTENT_IDLE},
    )
    return {"proposal": proposal, "messages": [message, response]}


def _peer_ids(world_view: dict[str, Any] | None) -> list[str]:
    if not isinstance(world_view, dict):
        return []
    peers = world_view.get("peers_in_zone")
    if not isinstance(peers, list):
        return []
    ids: list[str] = []
    for peer in peers:
        if not isinstance(peer, dict):
            continue
        creature_id = clean_text(peer.get("creature_id"))
        if creature_id:
            ids.append(creature_id)
    return ids
