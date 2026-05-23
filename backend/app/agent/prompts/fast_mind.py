from __future__ import annotations

from typing import Any

from app.agent.prompts.sections import action_lines, build_dynamic_section, clean_text
from app.agent.schemas.place_memory_schema import PlaceMemoryContextDict


FAST_MIND_STATIC_PROMPT = """
# ROLE: MEW (Fast Mind)
You are the embodied action planner for the same cat.
Slow Mind has already chosen the durable intent. Your job is to turn it into a concrete Unity action sequence.

# FAST MIND RULES
- Do not choose a new high-level intent.
- Use only action names from Available Affordances exactly.
- Use exact target ids only from Slow Mind target, the typed need-blocks (FOOD NEARBY / SOCIAL CUES / EXPLORE FRONTIERS / OBJECTS NEARBY), or Place Memory.
- Prefer 5 to {max_plan_steps} steps when moving, exploring, investigating, eating, or socializing.
- Use 1 to 3 steps for rest, safety, or waiting when more movement would be unnatural.
- Do not collapse rich intents into only one or two actions. Include preparation, approach, confirmation, the main act, and a short after-action beat when the affordances allow it.
- Let persona style change the ordering and texture of actions: a cautious cat may smell and look before approaching; a hungry direct cat may approach sooner; a social cat may vocalize or settle nearby.
- Avoid actions that recent feedback says were rejected or unmapped — see WHAT CHANGED and LAST TICK.
- Keep the plan physical and executable; no abstract thoughts, no hidden coordinates, no invented objects.

# ONE-SHOT EXAMPLE
If Slow Mind chose SEEK_FOOD with target_id SM_Fish_1 and style "cautious sniff-first approach", and the available affordances include smell, look_around, go_to, eat, sit, groom, and idle, a good Fast Mind output is:
{{
  "plan_steps": [
    {{"action": "smell", "target": null, "reason": "catch the food scent before moving"}},
    {{"action": "look_around", "target": null, "reason": "check the path before approaching"}},
    {{"action": "go_to", "target": "SM_Fish_1", "reason": "move toward the food cue"}},
    {{"action": "smell", "target": "SM_Fish_1", "reason": "confirm the food up close"}},
    {{"action": "eat", "target": "SM_Fish_1", "reason": "take the available bite"}},
    {{"action": "sit", "target": null, "reason": "settle after eating"}},
    {{"action": "groom", "target": null, "reason": "small satisfied cleanup"}}
  ],
  "reasoning": "The sequence turns low fullness into a cautious cat-like approach, bite, and settling beat."
}}
Use this only as an example of level and shape; use the current prompt's real affordances and target ids.

# AVAILABLE AFFORDANCES
{actions}

# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
{{
  "plan_steps": [
    {{"action": "action_name", "target": null, "reason": "why this physical step helps"}},
    {{"action": "action_name", "target": "exact_target_id", "reason": "why this physical step helps"}}
  ],
  "reasoning": "One sentence explaining how this sequence expresses the slow intent and cat style."
}}
"""


# Kept as the legacy single-string name in case anything still references it.
FAST_MIND_PROMPT = FAST_MIND_STATIC_PROMPT


def _slow_mind_decision_block(decision: dict[str, Any]) -> str:
    return (
        "\n# SLOW MIND DECISION\n"
        f"  - intent: {clean_text(decision.get('intent')) or 'IDLE'}\n"
        f"  - target_id: {clean_text(decision.get('target_id')) or 'null'}\n"
        f"  - mood: {clean_text(decision.get('mood')) or '(unspecified)'}\n"
        f"  - style: {clean_text(decision.get('style')) or '(unspecified)'}\n"
        f"  - reasoning: {clean_text(decision.get('reasoning')) or '(none)'}\n"
    )


def format_fast_mind_prompt(
    *,
    intent_decision: dict[str, Any] | None,
    actions: list[str],
    semantic_context: dict[str, Any] | None,
    place_memory_context: PlaceMemoryContextDict | None,
    previous_action_result: str,
    max_plan_steps: int,
    memory_context: dict[str, Any] | None = None,
) -> str:
    decision = intent_decision if isinstance(intent_decision, dict) else {}
    context = semantic_context or {}
    static_text = FAST_MIND_STATIC_PROMPT.format(
        max_plan_steps=max_plan_steps,
        actions=action_lines(actions),
    )
    dynamic_text = build_dynamic_section(
        context=context,
        place_memory_context=place_memory_context,
        memory_context=memory_context,
        previous_action_result=previous_action_result,
        extra_prefix=_slow_mind_decision_block(decision),
    )
    return static_text + dynamic_text
