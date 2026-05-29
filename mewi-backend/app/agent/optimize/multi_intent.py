"""
Primary + fallback intent for Slow Mind.

A cat that picks one rigid intent per tick is brittle: if the fish becomes
unreachable, the plan fails and the cat repicks SEEK_FOOD again next tick.
A real animal carries a backup ("if the fish is gone, I'll wander").

This module:
  - defines the augmented Slow Mind output schema (primary + fallback)
  - parses an LLM response into a `MultiIntentDecision`
  - coerces a legacy single-intent response so callers can switch over
    without breaking historical replay data

The Fast Mind / executor decides *when* to swap to the fallback — typically
when the primary's target resolution fails or the worker reports the plan
as `rejected`. That switching logic lives outside this module; here we
just provide the data shape and a clean parser.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.prompts.sections import clean_text


# Drop-in replacement for the OUTPUT FORMAT block when callers want the
# multi-intent shape. Same idea as chain_of_thought: prompt-only change.
SLOW_MIND_MULTI_INTENT_OUTPUT_BLOCK = """
# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
Pick a primary intent that resolves the highest-tension need, and a
fallback intent in case the primary becomes infeasible (target gone,
path blocked, rejection in WHAT CHANGED). The fallback must be
different from the primary, and should serve a different need so the
cat keeps living instead of looping.
{{
  "primary": {{
    "intent": "<EXPLORE | SEEK_FOOD | SEEK_PLAYER | SOCIALIZE | INVESTIGATE | REST | SAFETY | IDLE>",
    "target_id": null,
    "style": "short physical style hint for Fast Mind"
  }},
  "fallback": {{
    "intent": "<different intent>",
    "target_id": null,
    "style": "short physical style hint for Fast Mind"
  }},
  "mood": "brief embodied mood",
  "reasoning": "One sentence: why primary, why this fallback."
}}
"""


@dataclass(frozen=True)
class IntentChoice:
    intent: str
    target_id: str | None
    style: str

    @classmethod
    def from_dict(cls, value: Any) -> "IntentChoice":
        data = value if isinstance(value, dict) else {}
        target = clean_text(data.get("target_id"))
        return cls(
            intent=clean_text(data.get("intent")) or "IDLE",
            target_id=target or None,
            style=clean_text(data.get("style")),
        )


@dataclass(frozen=True)
class MultiIntentDecision:
    primary: IntentChoice
    fallback: IntentChoice
    mood: str
    reasoning: str

    def to_legacy_dict(self) -> dict[str, Any]:
        """Render as the legacy single-intent shape so downstream code that
        only knows the old schema keeps working. Uses the primary."""
        return {
            "intent": self.primary.intent,
            "target_id": self.primary.target_id,
            "mood": self.mood,
            "style": self.primary.style,
            "reasoning": self.reasoning,
        }


def coerce_to_multi_intent(response: Any) -> MultiIntentDecision:
    """
    Parse an LLM response into MultiIntentDecision.

    Handles three shapes:
      - native multi-intent: {"primary": {...}, "fallback": {...}, ...}
      - legacy single-intent: {"intent": "X", "target_id": "Y", ...}
      - empty / malformed: returns IDLE/IDLE so the cat does nothing rather
        than crashing the tick.

    For the legacy path the fallback is synthesised as IDLE so the cat
    has *some* second choice; callers that care should regenerate.
    """
    if not isinstance(response, dict):
        return _idle_pair()

    if "primary" in response:
        return MultiIntentDecision(
            primary=IntentChoice.from_dict(response.get("primary")),
            fallback=IntentChoice.from_dict(response.get("fallback")),
            mood=clean_text(response.get("mood")),
            reasoning=clean_text(response.get("reasoning")),
        )

    # Legacy single-intent shape — lift it as primary, fallback to IDLE.
    primary = IntentChoice(
        intent=clean_text(response.get("intent")) or "IDLE",
        target_id=clean_text(response.get("target_id")) or None,
        style=clean_text(response.get("style")),
    )
    return MultiIntentDecision(
        primary=primary,
        fallback=IntentChoice(intent="IDLE", target_id=None, style=""),
        mood=clean_text(response.get("mood")),
        reasoning=clean_text(response.get("reasoning")),
    )


def extract_primary_intent(decision: MultiIntentDecision) -> dict[str, Any]:
    """Convenience for Fast Mind: render just the primary as the legacy
    intent-decision dict shape it already consumes."""
    return decision.to_legacy_dict()


def _idle_pair() -> MultiIntentDecision:
    idle = IntentChoice(intent="IDLE", target_id=None, style="")
    return MultiIntentDecision(primary=idle, fallback=idle, mood="", reasoning="")
