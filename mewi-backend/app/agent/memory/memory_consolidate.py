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

from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent, TurnMemoryWrite
from app.agent.mind.context import clean_text, format_previous_action_result
from app.services.perception.semantic_service import SemanticService

if TYPE_CHECKING:  # avoid a runtime import cycle via creature_runtime -> memory
    from app.agent.creature_runtime import CreatureRuntimeState


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
    )


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
    previous = format_previous_action_result(raw.get("action_result"))
    intent = clean_text((state.get("intent_decision") or {}).get("intent"))
    text_parts = []
    if previous:
        text_parts.append(previous.replace("\n  - ", " ").replace("  - ", "").strip())
    plan_steps = state.get("plan_steps") or []
    proposals = [
        proposal for proposal in state.get("intent_proposals") or []
        if isinstance(proposal, dict)
    ]
    if intent and plan_steps:
        text_parts.append(f"Next intent {intent} became plan: {_plan_text(plan_steps)}.")
    elif intent:
        text_parts.append(f"Next intent {intent} was handed to Unity's directive FSM.")
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
    if not isinstance(action_result, dict):
        return 0.2
    status = clean_text(action_result.get("status")).lower()
    if status in {"failed", "rejected", "completed_with_failures", "completed_with_rejections"}:
        return 0.9
    if status == "completed_with_recoveries":
        return 0.6
    return 0.4


# ─── Consolidation: many AspectMemory -> one recap ───────────────────────────


_CONSOLIDATION_PROMPT = """You compress one cat's short-term memory so it stays small but useful.

Below are the older "{aspect}" memories for this cat, oldest first. Rewrite them
as ONE compact recap (1-2 short sentences) that keeps what still matters for the
cat's next decision — who and what it dealt with, how things went, and any
recent pattern — and drops repetition and stale detail.

Return only the recap text, with no quotes, labels, or extra lines.

MEMORIES:
{memories}"""


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
    prompt = _CONSOLIDATION_PROMPT.format(aspect=aspect, memories=lines)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return clean_text(getattr(response, "content", ""))
