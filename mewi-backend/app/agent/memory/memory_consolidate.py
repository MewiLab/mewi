"""Memory write-path and consolidation tools.

The :class:`~app.agent.memory.memory_manager.MemoryManager` delegates to the
two functions here; neither holds state of its own:

- :func:`build_turn_memory_write` -- deterministic turn -> ``TurnMemoryWrite``
  (the write path: what the cat did and heard this tick).
- :func:`consolidate_aspect_llm`  -- LLM compression of several
  ``AspectMemory`` entries into one compact recap.

Each tick appends one ``action`` and (when social) one ``social`` aspect
memory. Left alone these buckets grow into a long, repetitive wall of text
that crowds the prompt. ``consolidate_aspect_llm`` folds the older entries of
an overflowing bucket into a single recap; the manager keeps the few most
recent entries verbatim and writes the recap back in their place.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

from app.agent.memory.memory_models import (
    AspectMemory,
    MicroActionEvent,
    RawMemoryEvent,
    TurnMemoryWrite,
)
from app.agent.mind.context import clean_text
from app.agent.mind.experience import semantic_experience_events, semantic_experience_lines
from app.services.perception.semantic_service import SemanticService

if TYPE_CHECKING:  # avoid a runtime import cycle via creature_runtime -> memory
    from app.agent.creature_runtime import CreatureRuntimeState

logger = logging.getLogger(__name__)


# ─── Write path: turn -> memory ──────────────────────────────────────────────


def build_turn_memory_write(state: "CreatureRuntimeState") -> TurnMemoryWrite:
    raw = state.get("raw_payload", {}) or {}
    creature_id = clean_text(state.get("creature_id")) or clean_text(raw.get("agent_id"))
    tick = int(state.get("tick", 0) or 0)
    request_id = clean_text(raw.get("requestId"))
    semantic_context = SemanticService().build_prompt_context(raw)

    payload = {
        "request_id": request_id,
        "previous_action_result": raw.get("action_result"),
        "intent_decision": state.get("intent_decision") or {},
        "intent_proposals": state.get("intent_proposals") or [],
        "plan_steps": state.get("plan_steps") or [],
        "chosen_action": state.get("chosen_action") or {},
        "place_context": raw.get("place_context") or {},
        "spatial_context": raw.get("spatial_context") or {},
        "self": raw.get("self") or {},
        "mood": raw.get("mood") or {},
        "health": raw.get("health") or {},
        "feelings": raw.get("feelings") or {},
        "semantic_context": semantic_context,
        "reasoning": clean_text(state.get("reasoning")),
        "social_context": state.get("social_context") or {},
        "dialogue": state.get("dialogue") or [],
    }
    raw_event = RawMemoryEvent(
        creature_id=creature_id,
        tick=tick,
        request_id=request_id,
        source="python",
        event_type="planning_turn",
        payload=payload,
    )

    return TurnMemoryWrite(
        raw_event=raw_event,
        aspect_memories=_build_aspect_memories(
            tick=tick,
            raw=raw,
            state=state,
            semantic_context=semantic_context,
        ),
        micro_action_events=build_micro_action_events(state),
    )


def build_micro_action_events(state: "CreatureRuntimeState") -> list[MicroActionEvent]:
    """Normalize Unity's current live PlanExecutionReport into micro-actions.

    Phase 1 intentionally maps only fields Unity already sends. It does not
    synthesize player-cat stimulus lanes, lifecycle phases, or trust deltas.
    """
    raw = state.get("raw_payload", {}) or {}
    report = raw.get("action_result")
    if not isinstance(report, dict):
        _diagnose_normalizer("missing_field", reason="action_result_not_dict")
        return []

    steps = report.get("steps")
    live_events = report.get("events")
    if not isinstance(steps, list):
        steps = []
    if not isinstance(live_events, list):
        live_events = []
    if not steps and not live_events:
        _diagnose_normalizer("empty_steps", reason="report_steps_and_events_missing")
        return []

    creature_id = clean_text(state.get("creature_id")) or clean_text(raw.get("agent_id"))
    tick = int(state.get("tick", raw.get("tick", 0)) or 0)
    report_request_id = _first_text(
        report.get("requestId"),
        report.get("request_id"),
        raw.get("requestId"),
        raw.get("request_id"),
    )
    report_correlation_id = _first_text(
        report.get("correlationId"),
        report.get("correlation_id"),
    )
    actor_id = _first_text(report.get("agent_id"), report.get("agentId"), creature_id)
    known_cat_ids = _known_cat_ids(state, raw, creature_id)

    events: list[MicroActionEvent] = []
    for index, event_value in enumerate(live_events):
        if not isinstance(event_value, dict):
            _diagnose_normalizer("missing_field", reason="event_not_dict")
            continue
        normalized = _normalize_live_event(
            event_value,
            creature_id=creature_id,
            tick=tick,
            index=index,
            report_request_id=report_request_id,
            report_correlation_id=report_correlation_id,
            report_status=clean_text(report.get("status")),
            known_cat_ids=known_cat_ids,
        )
        if normalized is not None:
            events.append(normalized)

    for index, step_value in enumerate(steps):
        if not isinstance(step_value, dict):
            _diagnose_normalizer("missing_field", reason="step_not_dict")
            continue

        action = clean_text(step_value.get("action"))
        target_id = clean_text(step_value.get("target"))
        request_id = _first_text(
            step_value.get("requestId"),
            step_value.get("request_id"),
            report_request_id,
        )
        correlation_id = _first_text(
            step_value.get("correlationId"),
            step_value.get("correlation_id"),
            report_correlation_id,
        )
        event_id = _first_text(step_value.get("commandId"), step_value.get("command_id"))
        if not event_id:
            event_id = _fallback_event_id(
                creature_id=creature_id,
                request_id=request_id,
                step_index=index,
                action=action,
                target=target_id,
            )

        evidence = {
            "plan_id": _first_text(report.get("planId"), report.get("plan_id")),
            "report_status": clean_text(report.get("status")),
            "reason": clean_text(step_value.get("reason")),
            "started_at": _first_text(
                step_value.get("startedAt"),
                step_value.get("started_at"),
            ),
            "ended_at": _first_text(
                step_value.get("endedAt"),
                step_value.get("ended_at"),
            ),
            "report_started_at": _first_text(
                report.get("startedAt"),
                report.get("started_at"),
            ),
            "report_completed_at": _first_text(
                report.get("completedAt"),
                report.get("completed_at"),
            ),
            "step_index": index,
            "raw_step": step_value,
        }

        if not action:
            action = "unknown"
            evidence["normalization_status"] = "unknown_action"
            _diagnose_normalizer("unknown_action", reason="empty_action")

        target_type = _target_type(target_id, known_cat_ids)
        events.append(
            MicroActionEvent(
                creature_id=creature_id,
                event_id=event_id,
                correlation_id=correlation_id,
                request_id=request_id,
                tick=tick,
                actor_type="cat",
                actor_id=actor_id,
                target_type=target_type,
                target_id=target_id,
                direction=_direction("cat", target_type),
                action=action,
                behavior_key="",
                motor_action="",
                phase="",
                status=_first_text(step_value.get("status"), report.get("status")),
                source_event_id="",
                trust_delta=None,
                evidence=evidence,
            )
        )

    return events


def _normalize_live_event(
    event_value: dict[str, Any],
    *,
    creature_id: str,
    tick: int,
    index: int,
    report_request_id: str,
    report_correlation_id: str,
    report_status: str,
    known_cat_ids: set[str],
) -> MicroActionEvent | None:
    action = _first_text(event_value.get("action"), event_value.get("kind"))
    actor_type = _first_text(event_value.get("actor_type"), event_value.get("actorType"))
    actor_id = _first_text(event_value.get("actor_id"), event_value.get("actorId"))
    target_type = _first_text(event_value.get("target_type"), event_value.get("targetType"))
    target_id = _first_text(event_value.get("target_id"), event_value.get("targetId"))
    source_event_id = _first_text(
        event_value.get("source_event_id"),
        event_value.get("sourceEventId"),
    )

    if not target_type:
        target_type = _target_type(target_id, known_cat_ids)
    if not actor_type:
        actor_type = _actor_type(actor_id, creature_id, known_cat_ids)
    if not actor_id and actor_type == "cat":
        actor_id = creature_id
    direction = _first_text(event_value.get("direction"))
    if not direction:
        direction = _direction(actor_type, target_type)

    event_id = _first_text(
        event_value.get("event_id"),
        event_value.get("eventId"),
        event_value.get("commandId"),
        event_value.get("command_id"),
    )
    if not event_id:
        event_id = _fallback_event_id(
            creature_id=creature_id,
            request_id=report_request_id,
            step_index=index,
            action=action or "event",
            target=target_id,
        )

    if not action:
        action = "unknown"
        _diagnose_normalizer("unknown_action", reason="empty_live_event_action")

    return MicroActionEvent(
        creature_id=creature_id,
        event_id=event_id,
        correlation_id=_first_text(
            event_value.get("correlation_id"),
            event_value.get("correlationId"),
            report_correlation_id,
        ),
        request_id=_first_text(
            event_value.get("request_id"),
            event_value.get("requestId"),
            report_request_id,
        ),
        tick=tick,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        direction=direction,
        action=action,
        behavior_key=_first_text(
            event_value.get("behavior_key"),
            event_value.get("behaviorKey"),
        ),
        motor_action=_first_text(
            event_value.get("motor_action"),
            event_value.get("motorAction"),
        ),
        phase=_first_text(event_value.get("phase")),
        status=_first_text(event_value.get("status"), report_status),
        source_event_id=source_event_id,
        trust_delta=_float_or_none(
            event_value.get("trust_delta")
            if "trust_delta" in event_value
            else event_value.get("trustDelta")
        ),
        evidence={
            "event_index": index,
            "raw_event": event_value,
            "timestamp": event_value.get("timestamp"),
            "distance_m": event_value.get("distance_m") or event_value.get("distanceM"),
            "facing_dot": event_value.get("facing_dot") or event_value.get("facingDot"),
            "confidence": event_value.get("confidence"),
        },
    )


def _first_text(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def _fallback_event_id(
    *,
    creature_id: str,
    request_id: str,
    step_index: int,
    action: str,
    target: str,
) -> str:
    return ":".join(
        [
            creature_id or "unknown_cat",
            request_id or "unknown_request",
            str(step_index),
            action or "unknown_action",
            target or "none",
        ]
    )


def _known_cat_ids(
    state: "CreatureRuntimeState",
    raw: dict[str, Any],
    creature_id: str,
) -> set[str]:
    ids = {creature_id} if creature_id else set()
    for container in (
        state.get("dialogue") or [],
        (state.get("social_context") or {}).get("delivered_inbox") or [],
    ):
        if not isinstance(container, dict):
            continue
        for key in ("from", "target", "actor_id", "target_id"):
            value = clean_text(container.get(key))
            if value:
                ids.add(value)

    nearby = raw.get("nearby_entities")
    if isinstance(nearby, list):
        for entity in nearby:
            if not isinstance(entity, dict):
                continue
            for key in ("id", "name", "creature_id"):
                value = clean_text(entity.get(key))
                if value:
                    ids.add(value)
    return ids


def _target_type(target_id: str, known_cat_ids: set[str]) -> str:
    if not target_id:
        return ""
    lowered = target_id.lower()
    if lowered in {"player", "player_cat"}:
        return "player_cat"
    if target_id in known_cat_ids:
        return "cat"
    return ""


def _actor_type(actor_id: str, creature_id: str, known_cat_ids: set[str]) -> str:
    if not actor_id:
        return ""
    lowered = actor_id.lower()
    if lowered in {"player", "player_cat"}:
        return "player_cat"
    if actor_id == creature_id or actor_id in known_cat_ids:
        return "cat"
    return ""


def _direction(actor_type: str, target_type: str) -> str:
    if actor_type == "cat" and target_type == "cat":
        return "cat_to_cat"
    if actor_type == "cat" and target_type == "player_cat":
        return "cat_to_player_cat"
    if actor_type == "player_cat" and target_type == "cat":
        return "player_cat_to_cat"
    return ""


def _diagnose_normalizer(name: str, *, reason: str) -> None:
    logger.debug("micro_action_normalizer.%s reason=%s", name, reason)


def _build_aspect_memories(
    *,
    tick: int,
    raw: dict[str, Any],
    state: "CreatureRuntimeState",
    semantic_context: dict[str, Any],
) -> list[AspectMemory]:
    """
    STM is the *cross-tick* memory shown in the prompt. The per-tick body,
    place, and sensory blocks are already rendered fresh from the current
    snapshot, so echoing them into STM is pure duplication. We keep only the
    aspects that change tick to tick and aren't otherwise visible:

      - action: what plan ran and how it ended (history)
      - social: who has been around (continuity across ticks)

    body / place / sensory are intentionally dropped here.
    """
    memories: list[AspectMemory] = [_action_memory(tick, raw, state)]

    social = _social_memory(tick, raw, state, semantic_context)
    if social is not None:
        memories.append(social)

    return [memory for memory in memories if memory.text.strip()]


def _action_memory(
    tick: int,
    raw: dict[str, Any],
    state: "CreatureRuntimeState",
) -> AspectMemory:
    previous = _previous_action_fact(raw.get("action_result"))
    intent = clean_text((state.get("intent_decision") or {}).get("intent"))
    text_parts = []
    if previous:
        text_parts.append(previous.replace("\n  - ", " ").replace("  - ", "").strip())
    plan_steps = state.get("plan_steps") or []
    proposals = [
        proposal for proposal in state.get("intent_proposals") or []
        if isinstance(proposal, dict)
    ]
    if intent:
        target = clean_text((state.get("intent_decision") or {}).get("target_id"))
        suffix = f" near {target}" if target else ""
        text_parts.append(f"Current intention: {intent}{suffix}.")
    elif plan_steps:
        text_parts.append(f"Current intended body outline: {_plan_text(plan_steps)}.")
    elif proposals:
        text_parts.append(f"Domain proposals collected: {_proposal_text(proposals)}.")
    else:
        text_parts.append("No final intent was selected this tick.")
    return AspectMemory(
        aspect="action",
        text=" ".join(part for part in text_parts if part),
        tick=tick,
        salience=_action_salience(raw.get("action_result")),
        memory_kind="episodic",
        evidence={
            "previous_action_result": raw.get("action_result"),
            "intent": intent or "",
            "intent_proposals": proposals,
            "plan_steps": state.get("plan_steps") or [],
        },
    )


def _social_memory(
    tick: int,
    raw: dict[str, Any],
    state: "CreatureRuntimeState",
    semantic_context: dict[str, Any],
) -> AspectMemory | None:
    """Remember the actual conversation, falling back to nearby cues.

    What this cat said and what it heard from the inbox this turn are the
    only social signals that don't survive in the live snapshot, so they
    are the ones worth carrying across ticks.
    """
    conversation = _conversation_memory(tick, state)
    if conversation is not None:
        return conversation

    targets = semantic_context.get("relevant_targets")
    if not isinstance(targets, list):
        return None

    social_targets = [
        clean_text(target)
        for target in targets
        if any(word in clean_text(target).lower() for word in ["player", "human", "cat", "kitten"])
    ]
    if not social_targets:
        return None

    return AspectMemory(
        aspect="social",
        text="Nearby social cues: " + " ".join(social_targets[:3]),
        tick=tick,
        salience=0.3,
        memory_kind="working",
        evidence={"relevant_targets": social_targets[:5]},
    )


def _conversation_memory(
    tick: int,
    state: "CreatureRuntimeState",
) -> AspectMemory | None:
    social_context = state.get("social_context")
    if not isinstance(social_context, dict):
        return None

    lines: list[str] = []
    spoken = ""
    decision = social_context.get("decision")
    if isinstance(decision, dict) and decision.get("spoke"):
        spoken = _spoken_brief(decision.get("utterance"))
        if spoken:
            lines.append(f"You said {spoken}")

    heard: list[str] = []
    delivered = social_context.get("delivered_inbox")
    if isinstance(delivered, list):
        for item in delivered[-3:]:
            brief = _heard_brief(item)
            if brief:
                heard.append(brief)
                lines.append(f"Heard {brief}")

    if not lines:
        return None

    return AspectMemory(
        aspect="social",
        text=" ".join(lines),
        tick=tick,
        salience=0.5,
        memory_kind="episodic",
        evidence={"spoken": spoken, "heard": heard},
    )


def _spoken_brief(utterance: Any) -> str:
    if not isinstance(utterance, dict):
        return ""
    text = clean_text(utterance.get("text"))
    if not text:
        return ""
    target = clean_text(utterance.get("target"))
    return f'to {target}: "{text}"' if target else f'"{text}"'


def _heard_brief(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    text = clean_text(item.get("text"))
    if not text:
        return ""
    speaker = clean_text(item.get("from")) or "another cat"
    return f'{speaker}: "{text}"'


def _plan_text(plan_steps: list[dict[str, Any]]) -> str:
    if not plan_steps:
        return "idle"
    return " -> ".join(
        f"{step.get('action')}{(':' + step.get('target')) if step.get('target') else ''}"
        for step in plan_steps
    )


def _proposal_text(proposals: list[dict[str, Any]]) -> str:
    return ", ".join(
        f"{clean_text(item.get('domain')) or 'domain'}={clean_text(item.get('intent')) or 'IDLE'}"
        for item in proposals[:5]
    )


def _action_salience(action_result: Any) -> float:
    events = semantic_experience_events(action_result)
    if not events:
        return 0.2
    visible = [event for event in events if event.memory_policy != "audit_only"]
    if not visible:
        return 0.0
    return max((event.salience for event in visible), default=0.3)


def _previous_action_fact(action_result: Any) -> str:
    return " ".join(semantic_experience_lines(action_result))


def _step_facts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    facts: list[str] = []
    for step in value:
        if not isinstance(step, dict):
            continue
        action = clean_text(step.get("action")) or "unknown_action"
        target = clean_text(step.get("target"))
        status = clean_text(step.get("status"))
        reason = clean_text(step.get("reason"))
        text = action
        if target:
            text += f"({target})"
        if status:
            text += f"={status}"
        if reason:
            text += f" because {reason}"
        facts.append(text)
    return facts


def _event_facts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    facts: list[str] = []
    for event in value:
        if not isinstance(event, dict):
            continue
        action = clean_text(event.get("action")) or clean_text(event.get("kind")) or "event"
        actor = clean_text(event.get("actor_id")) or clean_text(event.get("actorId"))
        target = clean_text(event.get("target_id")) or clean_text(event.get("targetId"))
        phase = clean_text(event.get("phase")) or clean_text(event.get("status"))
        relation = ""
        if actor or target:
            relation = f" {actor or 'unknown_actor'}->{target or 'unknown_target'}"
        suffix = f" {phase}" if phase else ""
        facts.append(f"{action}{relation}{suffix}".strip())
    return facts


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


# ─── Consolidation: memory context -> one recap ──────────────────────────────


_CONSOLIDATION_PROMPT = """You maintain one cat's reflective long-term memory.

You are given this cat's recent short-term memories (ordered oldest->newest)
and any long-term memories recalled this tick. Produce ONE compact reflective
memory for the cat's next decision.

Follow these steps internally, then output only the final memory:

1. EVIDENCE: From the memories, pick the 2-4 facts most relevant to the next
   decision. Use only stated facts. The cat's CURRENT directive is shown below
   and MUST be reflected in the output.
2. INSIGHT: State one grounded, decision-relevant pattern, preference,
   constraint, or lesson supported by those facts. You may infer cautious
   meaning from REPEATED facts, but do not invent events, motives, emotions,
   hesitation, failure, or outcomes not explicitly stated. A fact that appears
   once is a single event - do not pluralize or generalize it.
3. WRITE: Compress into at most 2 sentences, 35 words total. No hedging or
   filler clauses (e.g. "which may influence my next actions"). Every clause
   must carry a fact or the insight.

Treat "selected next intent" as a future directive, not an attempted action.
If the new memories merely repeat a recalled long-term memory, add only what is
new.

Return only the memory text - no quotes, labels, citations, or extra lines.

CURRENT INTENTION (must appear in output):
{current_intention}

SHORT-TERM MEMORY (oldest->newest):
{short_term}

RELATED LONG-TERM MEMORY:
{related_memory}"""


async def consolidate_memory_llm(
    llm,
    memories: list[AspectMemory],
    *,
    related_memories: list[dict[str, Any]] | None = None,
) -> str:
    """Summarize all current Python-side short-term memory with recalled context."""
    if llm is None:
        return ""
    short_term_lines = "\n".join(
        f"- {memory.aspect} t={memory.tick}: {clean_text(memory.text)}"
        for memory in memories
        if memory.text.strip()
    )
    related_lines = _related_memory_lines(related_memories or [])
    if not short_term_lines and not related_lines:
        return ""
    prompt = _CONSOLIDATION_PROMPT.format(
        current_intention=_current_intention_line(memories),
        short_term=short_term_lines or "- (none)",
        related_memory=related_lines or "- (none)",
    )
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return clean_text(getattr(response, "content", ""))


async def consolidate_aspect_llm(
    llm,
    aspect: str,
    memories: list[AspectMemory],
) -> str:
    """Fold older AspectMemory entries for one aspect into a single recap.

    Returns the recap text, or ``""`` when there is no LLM or nothing to
    summarize. Only the LLM call awaits; the caller (MemoryManager) owns when
    to run this and how to write the result back.
    """
    if llm is None:
        return ""
    lines = "\n".join(f"- {clean_text(m.text)}" for m in memories if m.text.strip())
    if not lines:
        return ""
    prompt = _CONSOLIDATION_PROMPT.format(
        current_intention="- (not applicable for this aspect recap)",
        short_term=lines,
        related_memory="- (none)",
    )
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return clean_text(getattr(response, "content", ""))


def _current_intention_line(memories: list[AspectMemory]) -> str:
    """Hoist the newest action memory's intention so the prompt privileges it.

    ADR-040: recency weighting. The current directive is the intention carried by
    the most recent ``action`` memory. We prefer the structured ``evidence.intent``
    and fall back to the ``Current intention: ...`` clause in the text. When no
    action memory carries an intention, the field renders ``- (unknown)`` and the
    prompt's "must appear" clause is satisfied vacuously.
    """
    for memory in reversed(memories):
        if memory.aspect != "action":
            continue
        intent = clean_text((memory.evidence or {}).get("intent"))
        if intent:
            return f"- {intent}"
        clause = _intention_clause(memory.text)
        if clause:
            return f"- {clause}"
    return "- (unknown)"


def _intention_clause(text: str) -> str:
    marker = "Current intention:"
    idx = text.find(marker)
    if idx == -1:
        return ""
    clause = text[idx + len(marker):].strip().rstrip(".")
    return clean_text(clause)


def _related_memory_lines(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        text = clean_text(row.get("text"))
        if not text:
            continue
        aspect = clean_text(row.get("aspect")) or "memory"
        lines.append(f"- {aspect}: {text}")
    return "\n".join(lines)
