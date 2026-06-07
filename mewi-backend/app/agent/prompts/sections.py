from __future__ import annotations

from typing import Any

from app.agent.mind.experience import sanitize_agent_text
from app.agent.schemas.place_memory_schema import PlaceMemoryContextDict


def clean_text(value: Any) -> str:
    """Tiny string normaliser. Inlined here (rather than imported from
    app.agent.mind.context) so this module has no dependency on the mind
    package, which would create a prompts -> mind -> prompt_builder -> prompts
    import cycle."""
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


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
        return _dedupe_lines(sanitize_agent_text(line) for line in lines)

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
                result.append(sanitize_agent_text(f"{aspect}: {text}"))
    return _dedupe_lines(result)


def related_memory_lines(memory_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(memory_context, dict):
        return []
    rows = memory_context.get("longterm")
    if not isinstance(rows, list):
        return []
    lines: list[str] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        text = clean_text(row.get("text"))
        text = sanitize_agent_text(text)
        if not text:
            continue
        aspect = clean_text(row.get("aspect")) or "memory"
        lines.append(f"{aspect}: {text}")
    return _dedupe_lines(lines)


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
                cue
                for key, value in mood.items()
                if key in {"fear", "social", "trust"}
                and (cue := _mood_cue_text(key, value))
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

    feedback = social_context.get("social_feedback")
    if isinstance(feedback, list):
        for item in feedback[-4:]:
            line = _social_feedback_line(item)
            if line:
                lines.append(line)

    relationships = social_context.get("relationships")
    if isinstance(relationships, list):
        for relationship in relationships[:4]:
            line = relationship_memory_line(relationship)
            if line:
                lines.append(line)

    if lines:
        return _dedupe_lines(lines)

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


def _dedupe_lines(lines: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines or []:
        text = clean_text(raw)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


# Per-line prefixes used by app/agent/memory/place_memory_service._build_prompt_lines.
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
    view: str = "full",
) -> str:
    """
    Assemble the per-tick context as a sequence of typed need-blocks.
    Empty blocks are omitted so the model only sees signal it can act on.

    Block order is deliberate:
      WHERE -> BODY -> typed affordances/social -> SENSORY -> diff -> recent memory -> focus.

    extra_prefix lets callers paste a selector-specific block above the shared
    context without duplicating the rest of the layout.
    """
    situation = section_text(context.get("situation"))
    body_lines = context.get("body_lines") or []
    if not body_lines and context.get("body_state"):
        body_lines = [context.get("body_state")]
    food_nearby = _dedupe_lines(context.get("food_nearby") or [])
    social_cues = _dedupe_lines(context.get("social_cues") or [])
    other_cats = _dedupe_lines(world_view_lines(world_view))
    social_exchange = _dedupe_lines(social_context_lines(social_context))
    objects_nearby = _dedupe_lines(context.get("objects_nearby") or _meaningful_targets(context.get("relevant_targets")))
    objects_nearby = _remove_social_duplicates(objects_nearby, [*social_cues, *other_cats])
    explore_frontiers = _dedupe_lines(explore_frontier_lines(place_memory_context))
    sensory_world = _dedupe_lines(context.get("sensory_world") or [])
    whats_changed = _dedupe_lines(context.get("whats_changed") or [])
    decision_focus = _dedupe_lines(context.get("decision_focus") or [])

    current_place = current_place_line(place_memory_context)
    where_block = situation
    if current_place:
        where_block = f"{situation}\n{current_place}"

    view_key = (view or "full").lower()
    include_food = view_key in {"full", "need", "exploration"}
    include_social = view_key in {"full", "social"}
    include_explore = view_key in {"full", "exploration"}
    include_objects = view_key in {"full", "exploration"}
    include_sensory = view_key in {"full", "need", "exploration"}
    include_changed = view_key in {"full", "need"}
    include_recent = view_key == "full"

    last_tick_lines = _prompt_lines(previous_action_result)
    short_term_lines = short_term_memory_lines(memory_context)
    related_lines = related_memory_lines(memory_context)

    return (
        f"{extra_prefix}"
        f"\n# WHERE SHE IS\n{where_block}\n"
        f"{render_block('BODY', body_lines)}"
        f"{render_block('FOOD NEARBY', food_nearby) if include_food else ''}"
        f"{render_block('SOCIAL OPTIONS', social_cues) if include_social else ''}"
        f"{render_block('OTHER CATS HERE', other_cats) if include_social else ''}"
        f"{render_block('SOCIAL EXCHANGE', social_exchange) if include_social else ''}"
        f"{render_block('EXPLORE FRONTIERS', explore_frontiers) if include_explore else ''}"
        f"{render_block('OBJECTS NEARBY', objects_nearby) if include_objects else ''}"
        f"{render_block('SENSORY CUES (this tick)', sensory_world) if include_sensory else ''}"
        f"{render_block('WHAT CHANGED', whats_changed) if include_changed else ''}"
        f"{render_block('LAST TICK', last_tick_lines) if include_recent else ''}"
        f"{render_block('SHORT TERM MEMORY', short_term_lines) if include_recent else ''}"
        f"{render_block('RELATED MEMORY', related_lines)}"
        f"{render_block('DECISION FOCUS', decision_focus)}"
    )


def _prompt_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_lines = value.splitlines()
    elif isinstance(value, list):
        raw_lines = [str(item) for item in value]
    else:
        raw_lines = []
    cleaned: list[str] = []
    for raw in raw_lines:
        text = clean_text(raw)
        while text.startswith("-"):
            text = text[1:].strip()
        sanitized = sanitize_agent_text(text)
        if sanitized:
            cleaned.append(sanitized)
    return _dedupe_lines(cleaned)


def _remove_social_duplicates(objects: list[str], social_lines: list[str]) -> list[str]:
    targets = _target_ids_from_lines(social_lines)
    if not targets:
        return objects
    return [
        line for line in objects
        if not (
            "cat" in line.lower()
            and any(target.lower() in line.lower() for target in targets)
        )
    ]


def _target_ids_from_lines(lines: list[str]) -> set[str]:
    targets: set[str] = set()
    for line in lines:
        for match in _target_ids_in_line(line):
            targets.add(match)
    return targets


def _target_ids_in_line(line: str) -> list[str]:
    out: list[str] = []
    marker = "target:"
    lowered = line.lower()
    if marker not in lowered:
        return out
    tail = line[lowered.index(marker) + len(marker):]
    for raw in tail.replace(".", "").split(","):
        text = clean_text(raw)
        if text:
            out.append(text)
    return out


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


def _social_feedback_line(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    source = clean_text(value.get("from"))
    outcome = clean_text(value.get("outcome"))
    note = clean_text(value.get("note"))
    if not outcome:
        return ""
    if note:
        return f"Social feedback from {source or 'someone'}: {note}"
    return f"Social feedback from {source or 'someone'}: {outcome}."


def relationship_memory_line(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    pair = value.get("pair")
    pair_text = ", ".join(clean_text(item) for item in pair if clean_text(item)) \
        if isinstance(pair, list) else ""
    if not pair_text:
        return ""
    trust = _metric_text(value.get("trust"), kind="trust")
    affinity = _metric_text(value.get("affinity"), kind="affinity")
    encounters = value.get("encounters")
    parts = [f"bond {pair_text}"]
    if trust:
        parts.append(trust)
    if affinity:
        parts.append(affinity)
    if isinstance(encounters, int):
        parts.append(_encounter_text(encounters))
    return "; ".join(parts) + "."


def _meaningful_targets(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item).strip()
        for item in value
        if str(item).strip()
        and "no meaningful nearby target" not in str(item).lower()
    ]


def _metric_text(value: Any, *, kind: str) -> str:
    if not isinstance(value, (int, float)):
        return ""
    amount = float(value)
    if kind == "trust":
        label = _qualitative_band(
            amount,
            negative="trust is strained",
            low="trust is cautious",
            neutral="trust is still forming",
            high="trust is comfortable",
            strong="trust is strong",
        )
    else:
        label = _qualitative_band(
            amount,
            negative="affinity is chilly",
            low="affinity is tentative",
            neutral="affinity is neutral",
            high="affinity is warm",
            strong="affinity is close",
        )
    return label


def _mood_cue_text(key: str, value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    amount = float(value)
    if key == "fear":
        return _qualitative_band(
            amount,
            negative="fear is absent",
            low="fear is low",
            neutral="fear is mild",
            high="fear is high",
            strong="fear is very high",
            signed=False,
        )
    if key == "social":
        return _qualitative_band(
            amount,
            negative="social pull is absent",
            low="social pull is low",
            neutral="social pull is present",
            high="social pull is strong",
            strong="social pull is very strong",
            signed=False,
        )
    if key == "trust":
        return _metric_text(amount, kind="trust")
    return ""


def _qualitative_band(
    value: float,
    *,
    negative: str,
    low: str,
    neutral: str,
    high: str,
    strong: str,
    signed: bool = True,
) -> str:
    if not signed:
        if value < 0.05:
            return negative
        if value < 0.25:
            return low
        if value < 0.6:
            return neutral
        if value < 0.85:
            return high
        return strong
    if signed and value < -0.35:
        return negative
    if signed and value < -0.05:
        return low
    if value < 0.25:
        return neutral
    if value < 0.7:
        return high
    return strong


def _encounter_text(encounters: int) -> str:
    if encounters <= 0:
        return "no settled encounters yet"
    if encounters == 1:
        return "one encounter"
    if encounters < 4:
        return "a few encounters"
    return "many encounters"
