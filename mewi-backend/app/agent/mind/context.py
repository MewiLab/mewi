from __future__ import annotations

import json
from typing import Any

from app.agent.mind.experience import format_previous_action_feedback


__all__ = [
    "clean_text",
    "format_previous_action_result",
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
    return format_previous_action_feedback(value)
