from __future__ import annotations

from typing import Any

from app.agent.arbitration.helpers.domain_prompt import (
    build_domain_message,
    format_domain_context,
    parse_domain_intent,
)
from app.agent.mind.intents import INTENT_IDLE, INTENT_INVESTIGATE, INTENT_SEEK_PLAYER, INTENT_SOCIALIZE
from app.agent.prompts.sections import clean_text, relationship_memory_line


SOCIAL_PROPOSAL_PROMPT = """
# ROLE: MEW Social Proposal
You inspect nearby peers, relationship memory, and recent social exchange only.

# JOB
Return exactly one intent proposal for the social domain.
Choose SOCIALIZE for a viable nearby peer, SEEK_PLAYER for a human-seeking pull,
INVESTIGATE for a social cue that should be inspected first, or IDLE when social
context should not pull the cat now.
Use PERSONA to shape mood/style and sociability. Use PROCESSED SNAPSHOT CONTEXT,
MEMORY STATE, and COMMUNICATION FRAME for what is real right now. Do not invent a
peer, cue, target, utterance, or reaction.

# SPEECH RULES
social_act.say is communication, not decoration.
- Speak only when there is a concrete message grounded in the COMMUNICATION FRAME
  (a heard line, a place, a route, food, a body need, or a relationship cue).
- If there is no concrete message, leave "say" empty; body language or silence is
  a valid social act.
- Do not use generic animal noises (mew, mrrp, chirp) or bare greetings (hi,
  hello, come here) as standalone speech.
- Prefer replying to the latest delivered inbox line over starting a new topic.
- social_act is the speaker's intention only; never decide how the target reacts.

# DIALOGUE ACTS
Pick the "kind" that matches the message:
- reply: answer a delivered inbox line or recent direct transcript line.
- invite: ask the target to join, follow, inspect, rest, or share a place/object.
- check_in: low-pressure contact about a body/mood cue.
- share_cue: point out food, route, sound, smell, object, or place information.
- request: ask for space, help, following, waiting, or attention.
- boundary: communicate avoidance, fear, guarding food, or need for distance.
- greeting: only with a concrete cue attached, never a bare "hello".
- message: concrete speech that fits none of the above.

# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
{
  "intent": "<SOCIALIZE | SEEK_PLAYER | INVESTIGATE | IDLE>",
  "target_id": "<exact id from AVAILABLE INTENT AFFORDANCES, or null if none fits>",
  "mood": "brief embodied mood",
  "style": "short physical style hint",
  "social_act": {
    "kind": "reply | invite | check_in | share_cue | request | boundary | greeting | message",
    "say": "grounded communication, or empty string for body language only",
    "tone": "brief tone",
    "expects_reply": true
  },
  "reasoning": "one sentence explaining the social pull"
}
"""


# Allowed dialogue acts (ADR-039). Anything else collapses to "message".
SOCIAL_ACT_KINDS = {
    "reply",
    "invite",
    "check_in",
    "share_cue",
    "request",
    "boundary",
    "greeting",
    "message",
}

# Generic noises / bare greetings that are not valid standalone speech (ADR-039).
_GENERIC_SAY = {
    "mew", "mew?", "mrrp", "mrrp?", "chirp", "purr", "meow", "mrow", "mrowr",
    "hi", "hello", "hey", "yo", "come here", "hi!", "hello!",
}


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


def build_communication_frame(state: dict[str, Any]) -> list[str]:
    """Distill what this cat could meaningfully communicate this tick (ADR-039).

    Not a new source of truth - a prompt-facing slice of inbox, place, route,
    sensory/food, body, and relationship state that is already present. Lines are
    only emitted when the underlying data exists, so an empty frame nudges the
    model toward silence rather than generic chatter.
    """
    structured = state.get("structured_context") if isinstance(state, dict) else {}
    structured = structured if isinstance(structured, dict) else {}
    social_context = state.get("social_context")
    social_context = social_context if isinstance(social_context, dict) else {}
    semantic = structured.get("semantic_context")
    semantic = semantic if isinstance(semantic, dict) else {}

    lines: list[str] = []
    lines.extend(_heard_lines(social_context.get("delivered_inbox")))
    lines.extend(_sayable_cue_lines(structured, semantic))
    lines.extend(_relationship_lines(social_context.get("relationships")))
    return lines


async def propose_social_intent(llm: Any, state: dict[str, Any]) -> dict[str, Any]:
    frame = build_communication_frame(state)
    prompt = SOCIAL_PROPOSAL_PROMPT + _render_frame_block(frame) + format_domain_context(
        state,
        heading="Social domain: nearby peers, player pull, room context, relationship memory.",
        focus_lines=social_proposal_lines(state.get("world_view"), state.get("social_context")),
        view="social",
    )
    message = build_domain_message(prompt)
    response = await llm.ainvoke([message])
    proposal = parse_domain_intent(
        str(response.content),
        domain="social",
        affordances=state.get("intent_affordances"),
        allowed_intents={INTENT_SOCIALIZE, INTENT_SEEK_PLAYER, INTENT_INVESTIGATE, INTENT_IDLE},
    )
    _finalize_social_act(proposal, has_cue=bool(frame))
    return {"proposal": proposal, "messages": [message, response]}


def _finalize_social_act(proposal: dict[str, Any], *, has_cue: bool) -> None:
    """Enforce the ADR-039 speech contract on a parsed social proposal.

    Collapses unknown dialogue acts to ``message`` and blanks generic noises /
    bare greetings so they never reach the room as standalone speech. An empty
    ``say`` degrades the act to body language, which the publish step skips.
    """
    act = proposal.get("social_act")
    if not isinstance(act, dict):
        return

    if clean_text(act.get("kind")).lower() not in SOCIAL_ACT_KINDS:
        act["kind"] = "message"

    say = clean_text(act.get("say"))
    if _is_generic_say(say):
        say = ""
    act["say"] = say
    if not say:
        act["expects_reply"] = False

    # No concrete cue to ground speech: keep tone/style but drop the words.
    if say and not has_cue and act.get("kind") == "greeting":
        act["say"] = ""
        act["expects_reply"] = False


def _is_generic_say(say: str) -> bool:
    if not say:
        return False
    normalized = say.strip().strip("!.,~ ").lower()
    return normalized in _GENERIC_SAY


# ─── communication frame helpers ────────────────────────────────────────────


def _heard_lines(delivered_inbox: Any) -> list[str]:
    if not isinstance(delivered_inbox, list):
        return []
    lines: list[str] = []
    for item in delivered_inbox[-3:]:
        if not isinstance(item, dict):
            continue
        text = clean_text(item.get("text"))
        if not text:
            continue
        speaker = clean_text(item.get("from") or item.get("speaker_id")) or "a cat"
        kind = clean_text(item.get("kind"))
        prefix = f"Heard from {speaker}" + (f" ({kind})" if kind else "")
        lines.append(f'{prefix}: "{text}"')
    return lines


def _sayable_cue_lines(structured: dict[str, Any], semantic: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    place = structured.get("place")
    if isinstance(place, dict):
        current = clean_text(place.get("current_zone_id"))
        if current:
            lines.append(f"Sayable place cue: current place is {current}.")

    navigation = structured.get("navigation")
    if isinstance(navigation, dict):
        for route in _route_status_lines(navigation.get("zone_routes"))[:3]:
            lines.append(f"Sayable route cue: {route}.")

    for target in _food_targets(semantic.get("relevant_targets"))[:2]:
        lines.append(f"Sayable food cue: {target} is nearby.")

    for sensory in _string_list(semantic.get("sensory_world"))[:2]:
        lines.append(f"Sayable sense cue: {sensory}")

    signals = structured.get("signals")
    if isinstance(signals, dict):
        summary = clean_text(signals.get("summary"))
        if summary:
            lines.append(f"Sayable body cue: {summary}")
    return lines


def _relationship_lines(relationships: Any) -> list[str]:
    if not isinstance(relationships, list):
        return []
    lines: list[str] = []
    for item in relationships[:3]:
        line = relationship_memory_line(item)
        if line:
            lines.append(f"Relationship cue: {line}")
    return lines


def _render_frame_block(lines: list[str]) -> str:
    if not lines:
        return "\n# COMMUNICATION FRAME\n  - No concrete message is available; prefer silence or body language.\n"
    rendered = "\n".join(f"  - {line}" for line in lines)
    return f"\n# COMMUNICATION FRAME\n{rendered}\n"


def _route_status_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for route in value:
        if not isinstance(route, dict):
            continue
        route_id = clean_text(route.get("id"))
        if not route_id:
            continue
        status = clean_text(route.get("status")).lower()
        if status == "blocked":
            continue
        out.append(f"{route_id} is reachable ({status})" if status else f"{route_id} is reachable")
    return out


def _food_targets(value: Any) -> list[str]:
    food_words = ("fish", "mackerel", "food", "snack", "treat", "bowl", "kibble", "meat")
    out: list[str] = []
    for target in _string_list(value):
        if any(word in target.lower() for word in food_words):
            out.append(target)
    return out


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := clean_text(item))]


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
