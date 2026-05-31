from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage

from app.agent.mind.affordances import IntentAffordances, build_intent_affordances
from app.agent.mind.context import clean_text, normalize_target, parse_llm_json_object
from app.agent.mind.intents import INTENT_IDLE, normalize_intent
from app.agent.prompts.sections import build_dynamic_section


def build_domain_message(prompt: str) -> HumanMessage:
    return HumanMessage(content=prompt)


def format_domain_context(state: dict[str, Any], *, heading: str, focus_lines: list[str] | None = None) -> str:
    structured = state.get("structured_context") if isinstance(state, dict) else {}
    if not isinstance(structured, dict):
        structured = {}

    semantic_context = dict(structured.get("semantic_context") or {})
    if focus_lines:
        focus = list(semantic_context.get("decision_focus") or [])
        focus.extend(line for line in focus_lines if line)
        semantic_context["decision_focus"] = _dedupe(focus)

    return (
        f"\n# PERSONA\n{_persona_text(state)}\n"
        f"\n# DOMAIN\n{heading}\n"
        f"{_render_block('PROCESSED SNAPSHOT CONTEXT', _processed_snapshot_lines(structured))}"
        f"{_render_block('MEMORY STATE', _memory_state_lines(state.get('memory_state')))}"
        f"\n# AVAILABLE INTENT AFFORDANCES\n{_format_affordances(state.get('intent_affordances'))}\n"
        + build_dynamic_section(
            context=semantic_context,
            place_memory_context=state.get("place_memory_context"),
            memory_context=state.get("memory_context"),
            world_view=state.get("world_view"),
            social_context=state.get("social_context"),
            previous_action_result=clean_text(structured.get("previous_action_result")),
        )
    )


def parse_domain_intent(
    content: str,
    *,
    domain: str,
    affordances: IntentAffordances | dict[str, Any] | None,
    allowed_intents: set[str],
) -> dict[str, Any]:
    data = parse_llm_json_object(content)
    if not data:
        data = {
            "intent": INTENT_IDLE,
            "reasoning": f"{domain} proposal failed to parse.",
        }

    parsed_affordances = _coerce_affordances(affordances)
    intent = normalize_intent(data.get("intent"), default=INTENT_IDLE)
    if intent not in allowed_intents or not parsed_affordances.allows_intent(intent):
        intent = INTENT_IDLE

    target_id = normalize_target(data.get("target_id", data.get("target"))) or ""
    if target_id and not parsed_affordances.target_supports_intent(target_id, intent):
        target_id = ""

    parsed = {
        "domain": domain,
        "intent": intent,
        "target_id": target_id,
        "mood": clean_text(data.get("mood")),
        "style": clean_text(data.get("style")),
        "reasoning": clean_text(data.get("reasoning")) or f"{domain} proposed {intent}.",
    }
    social_act = _parse_social_act(data)
    if social_act:
        parsed["social_act"] = social_act
    return parsed


def _format_affordances(value: Any) -> str:
    aff = _coerce_affordances(value)
    intents = ", ".join(aff.available_intents) or INTENT_IDLE
    lines = [f"available_intents: {intents}"]
    if aff.targets:
        lines.append("targets:")
        lines.extend(f"  - {target.to_prompt_line()}" for target in aff.targets)
    else:
        lines.append("targets: none reported")
    return "\n".join(lines)


def _persona_text(state: dict[str, Any]) -> str:
    persona = clean_text(state.get("persona"))
    return persona or "No persona file was loaded; behave as a cautious, curious cat."


def _processed_snapshot_lines(structured: dict[str, Any]) -> list[str]:
    if not isinstance(structured, dict):
        return []
    lines: list[str] = []
    if structured.get("request_id"):
        lines.append(f"request_id: {clean_text(structured.get('request_id'))}")
    if structured.get("tick") is not None:
        lines.append(f"tick: {structured.get('tick')}")

    place = structured.get("place")
    if isinstance(place, dict):
        current = clean_text(place.get("current_zone_id"))
        if current:
            lines.append(f"current place: {current}")
        active = _string_list(place.get("active_zone_ids"))
        if active:
            lines.append(f"active places: {', '.join(active[:5])}")
        reachable = _string_list(place.get("reachable_zone_ids"))
        if reachable:
            lines.append(f"reachable places: {', '.join(reachable[:8])}")

    body = structured.get("body")
    if isinstance(body, dict):
        mood = _compact_mapping(body.get("mood"))
        health = _compact_mapping(body.get("health"))
        if mood:
            lines.append(f"mood signals: {mood}")
        if health:
            lines.append(f"health signals: {health}")

    signals = structured.get("signals")
    if isinstance(signals, dict):
        summary = clean_text(signals.get("summary"))
        if summary:
            lines.append(f"feeling summary: {summary}")
    return lines


def _memory_state_lines(memory_state: Any) -> list[str]:
    if not isinstance(memory_state, dict):
        return []

    lines: list[str] = []
    recent = memory_state.get("recent")
    if isinstance(recent, dict):
        for line in _string_list(recent.get("short_term_lines"))[:5]:
            lines.append(f"recent: {line}")

    working = memory_state.get("working")
    if isinstance(working, dict):
        aspects = [clean_text(key) for key in working.keys() if clean_text(key)]
        if aspects:
            lines.append(f"working aspects: {', '.join(aspects[:6])}")

    episodic = memory_state.get("episodic")
    if isinstance(episodic, list):
        for event in episodic[-3:]:
            if isinstance(event, dict):
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                intent = clean_text((payload.get("intent_decision") or {}).get("intent"))
                if intent:
                    lines.append(f"episodic: tick {event.get('tick')} had intent {intent}")

    spatial = memory_state.get("spatial")
    if isinstance(spatial, dict):
        place = spatial.get("place_memory")
        if isinstance(place, dict):
            for line in _string_list(place.get("lines"))[:4]:
                lines.append(f"spatial: {line}")

    relationship = memory_state.get("relationship")
    if isinstance(relationship, dict):
        social_context = relationship.get("social_context")
        if isinstance(social_context, dict):
            room = social_context.get("room")
            if isinstance(room, dict) and room.get("members"):
                lines.append(f"relationship room: {_json_compact(room.get('members'))}")
            for item in social_context.get("relationships") or []:
                if isinstance(item, dict):
                    lines.append(f"relationship: {_json_compact(item)}")
    return lines


def _render_block(header: str, lines: list[str]) -> str:
    clean_lines = [line for line in lines if clean_text(line)]
    if not clean_lines:
        return ""
    rendered = "\n".join(f"  - {line}" for line in clean_lines)
    return f"\n# {header}\n{rendered}\n"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := clean_text(item))]


def _compact_mapping(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    for key, raw in value.items():
        if isinstance(raw, float):
            parts.append(f"{key}={raw:.2f}")
        elif isinstance(raw, int):
            parts.append(f"{key}={raw}")
    return ", ".join(parts[:8])


def _json_compact(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return clean_text(value)


def _coerce_affordances(value: IntentAffordances | dict[str, Any] | None) -> IntentAffordances:
    if isinstance(value, IntentAffordances):
        return value
    if isinstance(value, dict):
        return build_intent_affordances(value)
    return build_intent_affordances({})


def _parse_social_act(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("social_act")
    if not isinstance(raw, dict):
        raw = {}

    say = clean_text(raw.get("say") or data.get("say"))
    tone = clean_text(raw.get("tone") or data.get("tone"))
    kind = clean_text(raw.get("kind")) or "message"
    expects_reply = raw.get("expects_reply", data.get("expects_reply"))

    if not say and not tone and kind == "message":
        return {}
    return {
        "kind": kind,
        "say": say,
        "tone": tone,
        "expects_reply": bool(expects_reply) if expects_reply is not None else bool(say),
    }


def _dedupe(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out
