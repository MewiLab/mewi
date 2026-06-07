from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.agent.prompts.sections import (
    build_dynamic_section as _build_dynamic_section,
)

if TYPE_CHECKING:
    from app.agent.schemas.place_memory_schema import PlaceMemoryContextDict


INTENT_SELECTION_PROMPT_STATIC = """
# ROLE: MEW (Intent Arbiter)
You are MEW, an autonomous digital cat embodied in a 3D environment.
Temperament: {temperament}. Trust Level: {trust}.

# PERSONA
{persona}

# INTENT CATALOG
- EXPLORE: curiosity carries the cat toward a new, stale, or interesting place.
- SEEK_FOOD: low fullness and a food cue guide the cat toward food.
- SEEK_PLAYER: the cat wants to locate or stay near a trusted human.
- SOCIALIZE: the cat wants gentle contact with a nearby cat.
- INVESTIGATE: the cat wants to inspect a nearby cue, object, smell, or sound.
- REST: low energy or comfort guides stillness, sitting, lying, or sleep.
- SAFETY: fear, danger, or failed movement guides distance or alertness.
- IDLE: no available intent is strong enough yet.

# ARBITRATION RULES
- Choose one high-level intent for Unity's ActionFSM, not a low-level action sequence.
- Use only an intent from AVAILABLE INTENT AFFORDANCES unless IDLE is the safest fallback.
- Use target_id only from AVAILABLE INTENT AFFORDANCES, social peers, or place-memory target ids.
- If a target lists supported intents, use it only with one of those intents.
- Prefer SEEK_FOOD when fullness is low and a food target is supported.
- Prefer EXPLORE when curiosity and energy are available, fullness is not urgent, and fear is low.
- Prefer SOCIALIZE when a nearby peer is viable, fear is low, and recent memory does not show social looping.
- Prefer REST when energy is low.
- Prefer SAFETY when fear or recent failed/rejected movement matters.
- Let mood and style describe the physical flavor Unity should bias toward.
- Do not invent coordinates, hidden objects, unsupported target ids, or motor actions.

# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
Replace placeholders with real values from the current context; do not return angle brackets.
{{
  "intent": "<EXPLORE | SEEK_FOOD | SEEK_PLAYER | SOCIALIZE | INVESTIGATE | REST | SAFETY | IDLE>",
  "target_id": null,
  "mood": "brief embodied mood",
  "style": "short ActionFSM style hint, e.g. cautious sniff-first, direct hungry approach, gentle social approach",
  "reasoning": "One sentence explaining why this intent fits."
}}

# EXAMPLES OF SHAPE ONLY
{{
  "intent": "EXPLORE",
  "target_id": "garden_corner",
  "mood": "curious",
  "style": "slow, sniffing path",
  "reasoning": "The cat has energy and the garden corner is a viable exploration target."
}}
{{
  "intent": "SOCIALIZE",
  "target_id": "cat_milo",
  "mood": "warm and alert",
  "style": "gentle approach with a soft greeting",
  "reasoning": "A familiar nearby cat is available and no urgent body need overrides the social pull."
}}
"""


INTENT_SELECTION_PROMPT = INTENT_SELECTION_PROMPT_STATIC


def format_intent_selection_prompt_parts(
    temperament: str,
    trust: str,
    semantic_context: dict | None = None,
    place_memory_context: "PlaceMemoryContextDict | None" = None,
    memory_context: dict | None = None,
    world_view: dict | None = None,
    social_context: dict | None = None,
    persona: str = "",
    previous_action_result: str = "",
    intent_affordances: Any = None,
) -> tuple[str, str]:
    """Return (static_prefix, dynamic_suffix) for prompt caching."""

    context = semantic_context or {}
    static_text = INTENT_SELECTION_PROMPT_STATIC.format(
        temperament=temperament,
        trust=trust,
        persona=persona.strip() or "No persona file was loaded; behave as a cautious, curious cat.",
    )
    dynamic_text = (
        "\n# AVAILABLE INTENT AFFORDANCES\n"
        f"{_format_affordances(intent_affordances)}\n"
        + _build_dynamic_section(
            context=context,
            place_memory_context=place_memory_context,
            memory_context=memory_context,
            world_view=world_view,
            social_context=social_context,
            previous_action_result=previous_action_result,
        )
    )
    return static_text, dynamic_text


def format_intent_selection_prompt(
    temperament: str,
    trust: str,
    semantic_context: dict | None = None,
    place_memory_context: "PlaceMemoryContextDict | None" = None,
    memory_context: dict | None = None,
    world_view: dict | None = None,
    social_context: dict | None = None,
    persona: str = "",
    previous_action_result: str = "",
    intent_affordances: Any = None,
) -> str:
    static_text, dynamic_text = format_intent_selection_prompt_parts(
        temperament=temperament,
        trust=trust,
        semantic_context=semantic_context,
        place_memory_context=place_memory_context,
        memory_context=memory_context,
        world_view=world_view,
        social_context=social_context,
        persona=persona,
        previous_action_result=previous_action_result,
        intent_affordances=intent_affordances,
    )
    return static_text + dynamic_text


def format_strategic_prompt(
    temperament: str,
    trust: str,
    position: str,
    current_action: str,
    mood: dict,
    health: dict,
    entities: list,
    actions: list,
    feelings: dict | None = None,
    semantic_context: dict | None = None,
    place_memory_context: "PlaceMemoryContextDict | None" = None,
    persona: str = "",
    previous_action_result: str = "",
) -> str:
    """Legacy entry point, now rendering the same intent-arbitration contract."""

    context = semantic_context or _legacy_semantic_context(
        position=position,
        current_action=current_action,
        mood=mood,
        health=health,
        entities=entities,
        feelings=feelings,
    )

    return format_intent_selection_prompt(
        temperament=temperament,
        trust=trust,
        semantic_context=context,
        place_memory_context=place_memory_context,
        persona=persona,
        previous_action_result=previous_action_result,
        intent_affordances={
            "available_intents": [
                "EXPLORE",
                "INVESTIGATE",
                "SEEK_FOOD",
                "SEEK_PLAYER",
                "SOCIALIZE",
                "REST",
                "SAFETY",
            ],
            "targets": [],
        },
    )


def _format_affordances(value: Any) -> str:
    if value is None:
        return "available_intents: IDLE\ntargets: none reported"

    if isinstance(value, dict):
        intents = value.get("available_intents")
        targets = value.get("targets")
    else:
        intents = getattr(value, "available_intents", None)
        targets = getattr(value, "targets", None)

    intent_text = ", ".join(str(item) for item in intents or []) or "IDLE"
    lines = [f"available_intents: {intent_text}"]

    target_lines: list[str] = []
    for target in targets or []:
        if hasattr(target, "to_prompt_line"):
            line = str(target.to_prompt_line()).strip()
            if line:
                target_lines.append(f"  - {line}")
            continue

        if isinstance(target, dict):
            target_id = str(target.get("id") or target.get("target_id") or "").strip()
            supports = target.get("supports") or []
            tags = target.get("tags") or []
            path_status = str(target.get("path_status") or target.get("status") or "").strip().lower()
            path_length = target.get("path_length")
        else:
            target_id = str(getattr(target, "id", "") or "").strip()
            supports = getattr(target, "supports", ()) or []
            tags = getattr(target, "tags", ()) or []
            path_status = str(getattr(target, "path_status", "") or "").strip().lower()
            path_length = getattr(target, "path_length", None)
        if not target_id:
            continue
        support_text = ", ".join(str(item) for item in supports) or "any listed intent"
        tag_text = f"; tags {', '.join(str(item) for item in tags[:4])}" if tags else ""
        path_text = _format_path_status(path_status, path_length)
        target_lines.append(f"  - {target_id}: supports {support_text}{tag_text}{path_text}")

    if target_lines:
        lines.append("targets:")
        lines.extend(target_lines)
    else:
        lines.append("targets: none reported")
    return "\n".join(lines)


def _format_path_status(status: str, path_length: Any) -> str:
    if not status:
        return ""
    if isinstance(path_length, (int, float)):
        return f"; path {status}, {float(path_length):.1f}m"
    return f"; path {status}"


def _legacy_semantic_context(
    position: str,
    current_action: str,
    mood: dict,
    health: dict,
    entities: list,
    feelings: dict | None,
) -> dict:
    fullness = _health_fullness(health)
    fear = _number(mood.get("fear") if isinstance(mood, dict) else None)
    energy = _number(mood.get("energy") if isinstance(mood, dict) else None, default=1.0)

    targets = []
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        target_id = str(entity.get("id") or "").strip()
        tags = [str(tag).split(".")[-1].replace("_", " ") for tag in entity.get("tags") or [] if tag]
        label = " and ".join(tags[:2]) or target_id
        if label:
            target = f"{label}"
            if target_id:
                target += f"; target: {target_id}"
            targets.append(target + ".")

    place = _semantic_place_text(position)
    return {
        "situation": f"The cat is {current_action or 'idle'} at {place}.",
        "body_state": _body_sentence(fullness, fear, energy),
        "sensory_world": _format_feeling_meanings(feelings),
        "relevant_targets": targets or ["No meaningful nearby target is currently visible."],
        "decision_focus": ["Choose a high-level ActionFSM intent that fits the interpreted situation."],
    }


def _semantic_place_text(position: str) -> str:
    text = str(position or "").strip()
    if not text:
        return "an unspecified place"
    if "x=" in text or "y=" in text or "z=" in text:
        return "the current area"
    return text


def _body_sentence(fullness: float, fear: float, energy: float) -> str:
    fullness = max(0.0, min(1.0, fullness))
    parts: list[str] = []
    if fullness >= 0.7:
        parts.append("fullness is high")
    elif fullness >= 0.3:
        parts.append("fullness is moderate")
    else:
        parts.append("fullness is low - food is urgent")
    parts.append("safety should come first" if fear >= 0.7 else "there is no strong fear signal")
    parts.append("energy is low" if energy <= 0.3 else "energy supports light movement")
    return ", ".join(parts) + "."


def _health_fullness(health: dict) -> float:
    if not isinstance(health, dict):
        return 1.0
    if "fullness" in health:
        return _number(health.get("fullness"), default=1.0)
    hunger = _number(health.get("hunger"), default=0.0)
    return 1.0 - max(0.0, min(1.0, hunger))


def _format_feeling_meanings(feelings: dict | None) -> list[str]:
    if not isinstance(feelings, dict):
        return ["No distinct smell, sound, or body-contact cue is reported right now."]

    lines: list[str] = []
    summary = str(feelings.get("summary") or "").strip()
    if summary:
        lines.append(summary)

    for key, label in [
        ("smells", "Smell"),
        ("sounds", "Sound"),
        ("signals", "Body signal"),
    ]:
        values = _string_values(feelings.get(key))
        lines.extend(f"{label}: {_meaningful_feeling(value)}." for value in values[:6])

    known = {"summary", "smells", "sounds", "signals"}
    for key, value in feelings.items():
        if key in known:
            continue
        values = _string_values(value)
        label = key.replace("_", " ").title()
        lines.extend(f"{label}: {_meaningful_feeling(item)}." for item in values[:4])

    return lines or ["No distinct smell, sound, or body-contact cue is reported right now."]


def _meaningful_feeling(value: str) -> str:
    text = str(value).strip()
    if ":" in text:
        _prefix, text = text.split(":", 1)
    return text.strip().replace("_", "-").rstrip(".")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]
