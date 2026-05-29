from __future__ import annotations

from typing import Any

from app.agent.creature_runtime import CreatureRuntimeState
from app.agent.memory.models import AspectMemory, RawMemoryEvent, TurnMemoryWrite
from app.agent.mind.context import clean_text, format_previous_action_result
from app.services.perception.semantic_service import SemanticService


def build_turn_memory_write(state: CreatureRuntimeState) -> TurnMemoryWrite:
    raw = state.get("raw_payload", {}) or {}
    creature_id = clean_text(state.get("creature_id")) or clean_text(raw.get("agent_id"))
    tick = int(state.get("tick", 0) or 0)
    request_id = clean_text(raw.get("requestId"))
    semantic_context = SemanticService().build_prompt_context(raw)

    payload = {
        "request_id": request_id,
        "previous_action_result": raw.get("action_result"),
        "intent_decision": state.get("intent_decision") or {},
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
    state: CreatureRuntimeState,
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

    social = _social_memory(tick, raw, semantic_context)
    if social is not None:
        memories.append(social)

    return [memory for memory in memories if memory.text.strip()]


def _action_memory(
    tick: int,
    raw: dict[str, Any],
    state: CreatureRuntimeState,
) -> AspectMemory:
    previous = format_previous_action_result(raw.get("action_result"))
    planned = _plan_text(state.get("plan_steps") or [])
    intent = clean_text((state.get("intent_decision") or {}).get("intent")) or "IDLE"
    text_parts = []
    if previous:
        text_parts.append(previous.replace("\n  - ", " ").replace("  - ", "").strip())
    text_parts.append(f"Next intent {intent} became plan: {planned}.")
    return AspectMemory(
        aspect="action",
        text=" ".join(part for part in text_parts if part),
        tick=tick,
        salience=_action_salience(raw.get("action_result")),
        memory_kind="episodic",
        evidence={
            "previous_action_result": raw.get("action_result"),
            "intent": intent,
            "plan_steps": state.get("plan_steps") or [],
        },
    )


def _social_memory(
    tick: int,
    raw: dict[str, Any],
    semantic_context: dict[str, Any],
) -> AspectMemory | None:
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


def _plan_text(plan_steps: list[dict[str, Any]]) -> str:
    if not plan_steps:
        return "idle"
    return " -> ".join(
        f"{step.get('action')}{(':' + step.get('target')) if step.get('target') else ''}"
        for step in plan_steps
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


