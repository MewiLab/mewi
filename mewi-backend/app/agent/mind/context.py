from __future__ import annotations

import json
from typing import Any


__all__ = [
    "available_action_names",
    "clean_text",
    "format_previous_action_result",
    "normalize_action",
    "normalize_plan_steps",
    "normalize_target",
    "parse_llm_json_object",
]


def parse_llm_json_object(content: str) -> dict[str, Any]:
    text = "" if content is None else str(content).strip()
    if text.startswith("```"):
        try:
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        except IndexError:
            return {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def available_action_names(actions: list[str] | tuple[str, ...] | None) -> set[str]:
    names: set[str] = set()
    for action in actions or []:
        name = clean_text(action).split(":", 1)[0].strip()
        if name:
            names.add(name)
    return names


def normalize_plan_steps(
    value: Any,
    *,
    available_actions: list[str] | tuple[str, ...] | set[str] | None = None,
    max_steps: int = 6,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    available = (
        available_actions
        if isinstance(available_actions, set)
        else available_action_names(list(available_actions or []))
    )
    filter_actions = bool(available)

    steps: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action = normalize_action(item.get("action"))
        if not action:
            continue
        if filter_actions and action not in available:
            continue
        steps.append({
            "action": action,
            "target": normalize_target(item.get("target", item.get("target_id"))),
            "reason": clean_text(item.get("reason")),
        })
        if len(steps) >= max_steps:
            break
    return steps


def normalize_action(value: Any) -> str:
    text = clean_text(value)
    if not text or text.lower() in {
        "action_name",
        "action_id",
        "immediate action_id to execute",
    }:
        return ""
    return text


def normalize_target(value: Any) -> str | None:
    text = clean_text(value)
    if not text or text.lower() in {
        "null",
        "none",
        "entity_id",
        "entity_id_or_null",
        "specific entity id, or null",
    }:
        return None
    return text


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def format_previous_action_result(value: Any) -> str:
    if not isinstance(value, dict):
        return ""

    status = clean_text(value.get("status")) or "unknown"
    lines = [_status_sentence(status)]

    steps = value.get("steps")
    if not isinstance(steps, list) or not steps:
        return "\n".join(f"  - {line}" for line in lines)

    for step in steps[:6]:
        if not isinstance(step, dict):
            continue
        action = clean_text(step.get("action")) or "unknown"
        step_status = clean_text(step.get("status")) or "unknown"
        target = clean_text(step.get("target"))
        reason = clean_text(step.get("reason"))
        lines.append(_step_recap(action, step_status, target, reason))
    return "\n".join(f"  - {line}" for line in lines)


def _status_sentence(status: str) -> str:
    if status in {"completed", "completed_with_recoveries"}:
        return "Your last small plan worked."
    if status in {"completed_with_rejections", "completed_with_failures"}:
        return "Your last plan partly worked."
    if status in {"failed", "rejected"}:
        return "Your last plan did not work; choose a smaller next step."
    return f"Your last plan ended as {status.replace('_', ' ')}."


def _step_recap(action: str, status: str, target: str, reason: str) -> str:
    target_text = target or ""

    if status == "rejected":
        if "unmapped_action" in reason:
            return f"You hesitated on {action}; your body did not know that action."
        return f"You hesitated on {action} ({_humanize_reason(reason)})."

    if action == "go_to":
        if status in {"completed", "recovered"}:
            return f"You walked to {target_text}." if target_text else "You walked over."
        if status == "failed":
            return (
                f"You tried to reach {target_text} but got stuck."
                if target_text
                else "You tried to move but got stuck."
            )

    if action == "eat":
        if status == "completed":
            return f"You took a bite from {target_text}." if target_text else "You took a bite."
        if status == "failed":
            return (
                f"You tried to eat {target_text} but couldn't reach it."
                if target_text
                else "You tried to eat but couldn't reach the food."
            )

    if action in {"follow", "investigate"}:
        if status in {"completed", "recovered"}:
            return f"You stayed near {target_text}." if target_text else "You stayed near it."
        if status == "failed":
            return f"You lost track of {target_text}." if target_text else "You lost track of it."

    if action == "drink" and status == "completed":
        return f"You drank from {target_text}." if target_text else "You took a drink."

    if status in {"completed", "recovered"}:
        verb = _self_verb_sentence(action)
        if verb:
            return verb

    if status == "failed":
        return f"You tried to {action.replace('_', ' ')} but it didn't take."

    return f"Your {action.replace('_', ' ')} ended as {status.replace('_', ' ')}."


def _self_verb_sentence(action: str) -> str:
    return {
        "idle": "You stayed still.",
        "wander": "You wandered for a moment.",
        "stop": "You stopped moving.",
        "stop_moving": "You stopped moving.",
        "sit": "You sat down.",
        "lie": "You lay down.",
        "sleep": "You rested.",
        "groom": "You groomed yourself.",
        "smell": "You sniffed the air.",
        "alert": "You became alert.",
        "look_around": "You scanned around.",
        "nod_head": "You tilted your head.",
        "vocalize": "You made a small sound.",
        "scratch": "You scratched.",
        "flinch": "You flinched.",
        "flee": "You moved away.",
    }.get(action, "")


def _humanize_reason(reason: str) -> str:
    text = clean_text(reason)
    if not text:
        return "no reason given"
    return text.replace("_", " ")
