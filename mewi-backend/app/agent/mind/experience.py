from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


TECHNICAL_PROMPT_TOKENS = (
    "Unity reported",
    "PlanExecutionReport",
    "adapter_refused",
    "rejected",
    "completed_with_rejections",
    "completed_with_failures",
    "failed",
    "TimedOut",
    "WarpedToNavMesh",
    "recovered_via_teleport",
    "backend",
    "integration",
    "raw_step",
    "Unity will execute the directive after this tick",
)

_TECHNICAL_REASON_TERMS = (
    "adapter",
    "unmapped_action",
    "unsupported_action",
    "unknown_action",
    "teleport",
    "warpedtonavmesh",
    "timedout",
    "timeout",
)
_SELECTED_INTENT_RE = re.compile(
    r"Selected next intent\s+(?P<intent>[A-Z_]+)(?:\s+toward\s+(?P<target>[^.;]+))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AgentExperienceEvent:
    """Agent-facing interpretation of one execution report item."""

    action: str
    target_id: str = ""
    outcome: str = "no_visible_change"
    visible_result: str = ""
    semantic_cause: str = ""
    salience: float = 0.0
    memory_policy: str = "audit_only"


def semantic_experience_events(action_result: Any) -> list[AgentExperienceEvent]:
    """Convert Unity execution reports into cat-visible experience.

    Raw adapter/body details stay in the journal and micro-action telemetry.
    This function returns only what the simulated cat could use as subjective
    memory or prompt context.
    """
    if not isinstance(action_result, dict):
        return []

    steps = action_result.get("steps")
    if not isinstance(steps, list):
        return []

    events: list[AgentExperienceEvent] = []
    for step in steps[:6]:
        if not isinstance(step, dict):
            continue
        action = _clean_text(step.get("action")) or "unknown"
        target = _clean_text(step.get("target"))
        status = _clean_text(step.get("status")).lower() or "unknown"
        reason = _clean_text(step.get("reason"))
        events.append(_semantic_step(action, target, status, reason))
    return events


def semantic_experience_lines(action_result: Any) -> list[str]:
    events = [
        event for event in semantic_experience_events(action_result)
        if event.memory_policy != "audit_only" and event.visible_result
    ]
    if not events:
        return []

    lines: list[str] = []
    has_done = any(event.outcome == "done" for event in events)
    has_blocked = any(event.outcome == "blocked" for event in events)
    if has_done and has_blocked:
        lines.append("Your last plan partly worked.")
    elif has_done:
        lines.append("Your last small plan worked.")
    elif has_blocked:
        lines.append("Your last action met a visible constraint; choose a smaller next step.")

    lines.extend(event.visible_result for event in events)
    return _dedupe(lines)


def format_previous_action_feedback(action_result: Any) -> str:
    return "\n".join(f"  - {line}" for line in semantic_experience_lines(action_result))


def sanitize_agent_text(value: Any) -> str:
    """Drop or rewrite old prompt text that leaks debug terminology."""
    text = _clean_text(value)
    if not text:
        return ""

    intent_line = _selected_intent_line(text)
    if _contains_technical_token(text):
        return intent_line

    if intent_line:
        return intent_line
    return text.replace("Selected next intent", "Current intention:")


def contains_technical_prompt_token(value: Any) -> bool:
    return _contains_technical_token(_clean_text(value))


def _semantic_step(
    action: str,
    target: str,
    status: str,
    reason: str,
) -> AgentExperienceEvent:
    if status in {"completed", "recovered"}:
        return AgentExperienceEvent(
            action=action,
            target_id=target,
            outcome="done",
            visible_result=_done_line(action, target),
            salience=_done_salience(action),
            memory_policy="episodic",
        )

    if status == "failed" and not _is_technical_reason(reason):
        return AgentExperienceEvent(
            action=action,
            target_id=target,
            outcome="blocked",
            visible_result=_blocked_line(action, target),
            semantic_cause=_semantic_reason(reason),
            salience=0.75,
            memory_policy="episodic",
        )

    return AgentExperienceEvent(
        action=action,
        target_id=target,
        outcome="no_visible_change",
        salience=0.0,
        memory_policy="audit_only",
    )


def _done_line(action: str, target: str) -> str:
    action_text = action.replace("_", " ")
    if action == "go_to":
        return f"You walked to {target}." if target else "You walked over."
    if action == "eat":
        return f"You took a bite from {target}." if target else "You took a bite."
    if action == "drink":
        return f"You drank from {target}." if target else "You took a drink."
    if action == "look_at":
        return f"You looked toward {target}." if target else "You looked around."
    if action == "vocalize":
        return f"You made a small sound toward {target}." if target else "You made a small sound."
    if action in {"follow", "investigate"}:
        return f"You stayed near {target}." if target else "You stayed near it."
    if action in {"sit", "lie", "sleep", "groom", "smell", "alert", "look_around", "flee"}:
        return _self_verb_sentence(action)
    return f"You completed {action_text}{(' near ' + target) if target else ''}."


def _blocked_line(action: str, target: str) -> str:
    action_text = action.replace("_", " ")
    if action == "go_to":
        return f"You could not reach {target}." if target else "You could not reach the target."
    if action == "eat":
        return (
            f"You tried to eat {target} but couldn't reach it."
            if target
            else "You tried to eat but couldn't reach the food."
        )
    if action in {"follow", "investigate"}:
        return f"You lost track of {target}." if target else "You lost track of it."
    return f"The {action_text} did not visibly change anything."


def _self_verb_sentence(action: str) -> str:
    return {
        "sit": "You sat down.",
        "lie": "You lay down.",
        "sleep": "You rested.",
        "groom": "You groomed yourself.",
        "smell": "You sniffed the air.",
        "alert": "You became alert.",
        "look_around": "You scanned around.",
        "flee": "You moved away.",
    }.get(action, f"You completed {action.replace('_', ' ')}.")


def _done_salience(action: str) -> float:
    if action in {"eat", "drink", "go_to"}:
        return 0.45
    if action in {"vocalize", "look_at", "follow", "investigate"}:
        return 0.5
    return 0.3


def _selected_intent_line(text: str) -> str:
    match = _SELECTED_INTENT_RE.search(text)
    if not match:
        return ""
    intent = _clean_text(match.group("intent")).upper()
    target = _clean_text(match.group("target"))
    if target:
        return f"Current intention: {intent} near {target}."
    return f"Current intention: {intent}."


def _contains_technical_token(text: str) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in TECHNICAL_PROMPT_TOKENS)


def _is_technical_reason(reason: str) -> bool:
    lowered = reason.replace("_", "").replace(":", "").lower()
    return any(term.replace("_", "").lower() in lowered for term in _TECHNICAL_REASON_TERMS)


def _semantic_reason(reason: str) -> str:
    text = _clean_text(reason).replace("_", " ")
    if not text or _is_technical_reason(text):
        return ""
    return text


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.lower()
        if not line or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out
