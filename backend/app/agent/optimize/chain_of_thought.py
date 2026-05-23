"""
Chain-of-thought scratchpad for Slow Mind.

Default Slow Mind output is one JSON object with a `reasoning` field. That
field is *consequent* — the model commits to an intent and then justifies it
in one sentence. For a cat that should balance competing drives (food vs
exploration vs rest vs social), we want the reasoning to come *before* the
commitment, and to mention the tradeoffs explicitly.

This module augments the Slow Mind output schema with a `thought` field
the model fills first, weighing each typed need-block (FOOD NEARBY,
SOCIAL CUES, EXPLORE FRONTIERS) against the current BODY state, before
emitting the intent.

Use:
    static_text = SLOW_MIND_PROMPT_STATIC.format(...)
    static_text = augment_slow_mind_with_cot(static_text)

The static text gains an OUTPUT FORMAT that includes the new field, and
the example output shows the structure. No LLM-side changes required.
"""
from __future__ import annotations

from typing import Any

# Drop-in replacement for the OUTPUT FORMAT block in SLOW_MIND_PROMPT_STATIC.
# The "thought" field is rendered *first* so the model writes its reasoning
# trace before settling on an intent. Constrained to one short paragraph to
# avoid runaway monologues.
SLOW_MIND_COT_OUTPUT_BLOCK = """
# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
Fill "thought" first — three to five sentences weighing the typed need-blocks
(FOOD NEARBY, SOCIAL CUES, EXPLORE FRONTIERS, OBJECTS NEARBY) against the
current BODY state. Mention the strongest competing need by name. Then pick
the intent that resolves the highest-tension drive with a viable affordance.
{{
  "thought": "Short reasoning trace, 3-5 sentences. Mention competing needs.",
  "intent": "<EXPLORE | SEEK_FOOD | SEEK_PLAYER | SOCIALIZE | INVESTIGATE | REST | SAFETY | IDLE>",
  "target_id": null,
  "mood": "brief embodied mood",
  "style": "short physical style hint for Fast Mind",
  "reasoning": "One sentence summarizing the chosen intent."
}}
"""


def augment_slow_mind_with_cot(static_prompt_text: str) -> str:
    """
    Replace the OUTPUT FORMAT block in a rendered Slow Mind static prompt
    with the CoT variant. Returns the augmented text unchanged if the
    expected marker isn't found (defensive, so this is safe to call on
    arbitrary prompt strings).
    """
    marker = "# OUTPUT FORMAT"
    idx = static_prompt_text.rfind(marker)
    if idx < 0:
        return static_prompt_text
    prefix = static_prompt_text[:idx].rstrip()
    return f"{prefix}\n{SLOW_MIND_COT_OUTPUT_BLOCK.strip()}\n"


def extract_thought(decision: dict[str, Any] | None) -> str:
    """Pull the scratchpad text out of a Slow Mind JSON response.

    Returns "" when the field is missing or empty — callers should treat
    that as "model fell back to one-sentence reasoning."
    """
    if not isinstance(decision, dict):
        return ""
    raw = decision.get("thought")
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.strip().split())
