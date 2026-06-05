from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.arbitration.helpers.domain_prompt import (
    build_domain_message,
    format_domain_context,
    parse_domain_intent,
)
from app.agent.arbitration.helpers.life_balance import life_balance_focus_lines
from app.agent.mind.intents import INTENT_IDLE, INTENT_REST, INTENT_SAFETY, INTENT_SEEK_FOOD
from app.agent.prompts.sections import clean_text


NEED_ASSESSMENT_PROMPT = """
# ROLE: MEW Need Proposal
You inspect body pressure and neglected drives only.

# JOB
Return exactly one intent proposal for the need domain.
Choose SEEK_FOOD for hunger, REST for low energy, SAFETY for fear/danger, or IDLE
when no body/need pressure should drive the next decision.
Use PERSONA to shape mood/style and thresholds, but let body pressure and
MEMORY STATE decide whether this domain should pull. Use PROCESSED SNAPSHOT
CONTEXT as the cleaned source of current mood, health, and place facts.

# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
{
  "intent": "<SEEK_FOOD | REST | SAFETY | IDLE>",
  "target_id": "<exact id from AVAILABLE INTENT AFFORDANCES, or null if none fits>",
  "mood": "brief embodied mood",
  "style": "short physical style hint",
  "reasoning": "one sentence explaining the need pressure"
}
"""


@dataclass(frozen=True)
class NeedAssessment:
    """Small, prompt-ready view of current body pressure and neglected drives."""

    focus_lines: tuple[str, ...]


def assess_needs(
    semantic_context: dict[str, Any] | None,
    memory_context: dict[str, Any] | None,
) -> NeedAssessment:
    context = semantic_context if isinstance(semantic_context, dict) else {}
    lines: list[str] = []

    for line in context.get("body_lines") or []:
        text = clean_text(line)
        lowered = text.lower()
        if not text:
            continue
        if "urgent" in lowered or "low" in lowered or "fear" in lowered:
            lines.append(f"Need assessment: {text}")

    lines.extend(life_balance_focus_lines(memory_context))
    return NeedAssessment(focus_lines=tuple(_dedupe(lines)))


async def propose_need_intent(llm: Any, state: dict[str, Any]) -> dict[str, Any]:
    structured = state.get("structured_context") if isinstance(state, dict) else {}
    semantic = structured.get("semantic_context") if isinstance(structured, dict) else {}
    assessment = assess_needs(semantic, state.get("memory_context"))
    prompt = NEED_ASSESSMENT_PROMPT + format_domain_context(
        state,
        heading="Need domain: body pressure, fear, fatigue, hunger, neglected drives.",
        focus_lines=list(assessment.focus_lines),
    )
    message = build_domain_message(prompt)
    response = await llm.ainvoke([message])
    proposal = parse_domain_intent(
        str(response.content),
        domain="need",
        affordances=state.get("intent_affordances"),
        allowed_intents={INTENT_SEEK_FOOD, INTENT_REST, INTENT_SAFETY, INTENT_IDLE},
    )
    return {"proposal": proposal, "messages": [message, response]}


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out
