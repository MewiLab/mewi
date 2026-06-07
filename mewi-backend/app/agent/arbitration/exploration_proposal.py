from __future__ import annotations

from typing import Any

from app.agent.arbitration.helpers.domain_prompt import (
    build_domain_message,
    format_domain_context,
    parse_domain_intent,
)
from app.agent.mind.intents import INTENT_EXPLORE, INTENT_IDLE, INTENT_INVESTIGATE
from app.agent.prompts.sections import clean_text, explore_frontier_lines


EXPLORATION_PROPOSAL_PROMPT = """
# ROLE: MEW Exploration Proposal
You inspect curiosity, novelty, place memory, and reachable targets only.

# JOB
Return exactly one intent proposal for the exploration domain.
Choose EXPLORE for a viable new/stale place, INVESTIGATE for a nearby object or
cue worth inspecting, or IDLE when exploration should not pull the cat now.
Use PERSONA to shape mood/style and how strongly curiosity pulls, but do not
invent targets or actions. Use PROCESSED SNAPSHOT CONTEXT for current body/place
facts, and MEMORY STATE for spatial history and recent patterns.

# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
{
  "intent": "<EXPLORE | INVESTIGATE | IDLE>",
  "target_id": "<exact id from AVAILABLE INTENT AFFORDANCES, or null if none fits>",
  "mood": "brief embodied mood",
  "style": "short physical style hint",
  "reasoning": "one sentence explaining the curiosity/place pull"
}
"""


def exploration_proposal_lines(
    place_memory_context: dict[str, Any] | None,
) -> list[str]:
    """Return one or two compact EXPLORE hints from place memory."""

    proposals: list[str] = []
    for line in explore_frontier_lines(place_memory_context):
        text = clean_text(line)
        if not text:
            continue
        if text.startswith("Best exploration target:"):
            proposals.insert(0, f"Exploration proposal: {text}")
        elif "not visited" in text.lower() or "least recent" in text.lower():
            proposals.append(f"Exploration proposal: {text}")
        if len(proposals) >= 2:
            break
    return proposals


async def propose_exploration_intent(llm: Any, state: dict[str, Any]) -> dict[str, Any]:
    prompt = EXPLORATION_PROPOSAL_PROMPT + format_domain_context(
        state,
        heading="Exploration domain: curiosity, objects, frontiers, novelty, place memory.",
        focus_lines=exploration_proposal_lines(state.get("place_memory_context")),
        view="exploration",
    )
    message = build_domain_message(prompt)
    response = await llm.ainvoke([message])
    proposal = parse_domain_intent(
        str(response.content),
        domain="exploration",
        affordances=state.get("intent_affordances"),
        allowed_intents={INTENT_EXPLORE, INTENT_INVESTIGATE, INTENT_IDLE},
    )
    return {"proposal": proposal, "messages": [message, response]}
