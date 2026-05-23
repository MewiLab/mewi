from __future__ import annotations

from typing import Any

from app.agent.schemas.place_memory_schema import PlaceMemoryContextDict


def clean_text(value: Any) -> str:
    """Tiny string normaliser. Inlined here (rather than imported from
    app.agent.mind.context) so this module has no dependency on the mind
    package, which would create a prompts → mind → prompt_builder → prompts
    import cycle."""
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def action_lines(actions: list[str]) -> str:
    lines = [f"  - {clean_text(action)}" for action in actions if clean_text(action)]
    return "\n".join(lines) if lines else "  - idle\n  - wander\n  - go_to"


def bullet_lines(value: Any, *, empty: str = "  - (none)") -> str:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
    return "\n".join(f"  - {item}" for item in items) if items else empty


def place_memory_lines(place_memory_context: PlaceMemoryContextDict | None) -> list[str]:
    if not isinstance(place_memory_context, dict):
        return []

    lines = place_memory_context.get("lines")
    if isinstance(lines, list):
        return [str(line).strip() for line in lines if str(line).strip()]
    return []


def short_term_memory_lines(memory_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(memory_context, dict):
        return []

    lines = memory_context.get("short_term_lines")
    if isinstance(lines, list):
        return [str(line).strip() for line in lines if str(line).strip()]

    short_term = memory_context.get("short_term")
    if not isinstance(short_term, dict):
        return []

    result: list[str] = []
    for aspect, items in short_term.items():
        if not isinstance(items, list):
            continue
        for item in items[-2:]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                result.append(f"{aspect}: {text}")
    return result


def world_view_lines(world_view: dict[str, Any] | None) -> list[str]:
    if not isinstance(world_view, dict):
        return []

    peers = world_view.get("peers_in_zone")
    if not isinstance(peers, list):
        return []

    lines: list[str] = []
    for peer in peers[:6]:
        if not isinstance(peer, dict):
            continue
        creature_id = clean_text(peer.get("creature_id"))
        if not creature_id:
            continue
        line = f"{creature_id} is here"
        last_action = clean_text(peer.get("last_action"))
        last_target = clean_text(peer.get("last_action_target"))
        if last_action:
            line += f"; last did {last_action}"
            if last_target:
                line += f" near {last_target}"
        mood = peer.get("mood")
        if isinstance(mood, dict):
            cues = [
                f"{key}={float(value):.2f}"
                for key, value in mood.items()
                if key in {"fear", "social", "trust"}
                and isinstance(value, (int, float))
            ]
            if cues:
                line += f"; mood cues: {', '.join(cues[:3])}"
        lines.append(line + ".")
    return lines


def social_context_lines(social_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(social_context, dict):
        return []

    lines: list[str] = []
    delivered = social_context.get("delivered_inbox")
    if isinstance(delivered, list):
        for item in delivered[-4:]:
            line = _utterance_line(item, prefix="Heard")
            if line:
                lines.append(line)

    decision = social_context.get("decision")
    if isinstance(decision, dict) and decision.get("spoke"):
        utterance = decision.get("utterance")
        line = _utterance_line(utterance, prefix="You expressed")
        if line:
            lines.append(line)

    relationships = social_context.get("relationships")
    if isinstance(relationships, list):
        for relationship in relationships[:4]:
            if not isinstance(relationship, dict):
                continue
            pair = relationship.get("pair")
            pair_text = ", ".join(clean_text(item) for item in pair if clean_text(item)) \
                if isinstance(pair, list) else ""
            if not pair_text:
                continue
            trust = _metric_text(relationship.get("trust"))
            affinity = _metric_text(relationship.get("affinity"))
            encounters = relationship.get("encounters")
            parts = [f"bond {pair_text}"]
            if trust:
                parts.append(f"trust {trust}")
            if affinity:
                parts.append(f"affinity {affinity}")
            if isinstance(encounters, int):
                parts.append(f"{encounters} encounter(s)")
            lines.append("; ".join(parts) + ".")

    if lines:
        return lines

    room = social_context.get("room")
    if isinstance(room, dict):
        recent = room.get("recent_transcript")
        if isinstance(recent, list):
            return [
                line for item in recent[-4:]
                if (line := _utterance_line(item, prefix="Recent"))
            ]
    return []


def section_text(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "(unknown)"


def render_block(header: str, lines: Any) -> str:
    """
    Render a section as either an empty string (block hidden) or
    "\n# HEADER\n  - line1\n  - line2\n". Absence of a header is itself a
    signal — fewer tokens than printing "(none)" everywhere.
    """
    if isinstance(lines, str):
        items = [lines.strip()] if lines.strip() else []
    elif isinstance(lines, list):
        items = [str(item).strip() for item in lines if str(item).strip()]
    else:
        items = []
    if not items:
        return ""
    rendered = "\n".join(f"  - {item}" for item in items)
    return f"\n# {header}\n{rendered}\n"


# Per-line prefixes used by app/services/place_memory_service._build_prompt_lines.
# Kept here so the prompt layer can split that paragraph into typed blocks
# without re-parsing zone overlays.
_FRONTIER_LINE_PREFIXES = (
    "Recently visited",
    "Known places",
    "Nearby but not visited yet",
    "Least recent nearby places",
    "Known but not visited yet",
    "Best exploration target",
    "No reachable place list",
)


def current_place_line(place_memory_context: PlaceMemoryContextDict | None) -> str:
    """Pluck the 'Current place: X feels Y' line from PMC, if present."""
    for line in place_memory_lines(place_memory_context):
        if line.startswith("Current place:"):
            return line
    return ""


def explore_frontier_lines(place_memory_context: PlaceMemoryContextDict | None) -> list[str]:
    """Group all 'where could I go' lines from PMC into one block."""
    out: list[str] = []
    for line in place_memory_lines(place_memory_context):
        if any(line.startswith(prefix) for prefix in _FRONTIER_LINE_PREFIXES):
            out.append(line)
    return out


def build_dynamic_section(
    *,
    context: dict[str, Any],
    place_memory_context: PlaceMemoryContextDict | None,
    memory_context: dict[str, Any] | None,
    world_view: dict[str, Any] | None = None,
    social_context: dict[str, Any] | None = None,
    previous_action_result: str,
    extra_prefix: str = "",
) -> str:
    """
    Assemble the per-tick context as a sequence of typed need-blocks.
    Empty blocks are omitted so the model only sees signal it can act on.

    Block order is deliberate:
      WHERE → BODY → typed affordances/social → SENSORY → diff → LAST TICK → STM → focus.

    extra_prefix lets Fast Mind paste its "SLOW MIND DECISION" block above
    the shared context without duplicating the rest of the layout.

    Lives in sections.py (not prompts/__init__.py) so that prompts/fast_mind.py
    can import it without triggering the prompts → mind → prompts cycle.
    """
    situation = section_text(context.get("situation"))
    body_lines = context.get("body_lines") or []
    food_nearby = context.get("food_nearby") or []
    social_cues = context.get("social_cues") or []
    other_cats = world_view_lines(world_view)
    social_exchange = social_context_lines(social_context)
    objects_nearby = context.get("objects_nearby") or []
    explore_frontiers = explore_frontier_lines(place_memory_context)
    sensory_world = context.get("sensory_world") or []
    whats_changed = context.get("whats_changed") or []
    decision_focus = context.get("decision_focus") or []

    current_place = current_place_line(place_memory_context)
    where_block = situation
    if current_place:
        where_block = f"{situation}\n{current_place}"

    last_tick_block = (previous_action_result or "").rstrip() or "  - no previous plan result"
    short_term_lines = short_term_memory_lines(memory_context)

    return (
        f"{extra_prefix}"
        f"\n# WHERE SHE IS\n{where_block}\n"
        f"{render_block('BODY', body_lines)}"
        f"{render_block('FOOD NEARBY', food_nearby)}"
        f"{render_block('SOCIAL CUES', social_cues)}"
        f"{render_block('OTHER CATS HERE', other_cats)}"
        f"{render_block('SOCIAL EXCHANGE', social_exchange)}"
        f"{render_block('EXPLORE FRONTIERS', explore_frontiers)}"
        f"{render_block('OBJECTS NEARBY', objects_nearby)}"
        f"{render_block('SENSORY CUES (this tick)', sensory_world)}"
        f"{render_block('WHAT CHANGED', whats_changed)}"
        f"\n# LAST TICK\n{last_tick_block}\n"
        f"{render_block('SHORT TERM MEMORY', short_term_lines)}"
        f"{render_block('DECISION FOCUS', decision_focus)}"
    )


def _utterance_line(value: Any, *, prefix: str) -> str:
    if not isinstance(value, dict):
        return ""
    speaker = clean_text(value.get("from") or value.get("speaker_id"))
    text = clean_text(value.get("text"))
    target = clean_text(value.get("target") or value.get("target_id"))
    tone = clean_text(value.get("tone"))
    if not text:
        return ""
    subject = speaker if speaker else "someone"
    if prefix == "You expressed":
        line = f"{prefix}: {text}"
    else:
        line = f"{prefix} {subject}: {text}"
    if target:
        line += f" (toward {target})"
    if tone:
        line += f" [{tone}]"
    return line + "."


def _metric_text(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{float(value):+.2f}"
