from __future__ import annotations

from app.agent.arbitration import (
    assess_needs,
    exploration_proposal_lines,
    social_proposal_lines,
)
from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.mind.affordances import IntentAffordances, build_intent_affordances
from app.agent.mind.context import format_previous_action_result
from app.agent.prompts import format_intent_selection_prompt_parts
from app.services.perception.semantic_service import SemanticService


__all__ = ["build_intent_selection_prompt_parts"]


def build_intent_selection_prompt_parts(
    state: CreatureRuntimeState,
    runtime: CreatureRuntime,
) -> tuple[str, str, IntentAffordances]:
    raw = state.get("raw_payload", {})
    semantic_context = SemanticService().build_prompt_context(raw)
    _inject_arbitration_focus(
        semantic_context,
        memory_context=state.get("memory_context"),
        place_memory_context=state.get("place_memory_context"),
        world_view=state.get("world_view"),
        social_context=state.get("social_context"),
    )
    affordances = build_intent_affordances(
        raw,
        semantic_context=semantic_context,
        place_memory_context=state.get("place_memory_context"),
        world_view=state.get("world_view"),
    )
    static_text, dynamic_text = format_intent_selection_prompt_parts(
        temperament="curious",
        trust="unknown",
        semantic_context=semantic_context,
        place_memory_context=state.get("place_memory_context"),
        memory_context=state.get("memory_context"),
        world_view=state.get("world_view"),
        social_context=state.get("social_context"),
        persona=state.get("persona") or runtime.persona,
        previous_action_result=format_previous_action_result(raw.get("action_result")),
        intent_affordances=affordances,
    )
    return static_text, dynamic_text, affordances


def _inject_arbitration_focus(
    semantic_context: dict,
    *,
    memory_context: dict | None,
    place_memory_context: dict | None,
    world_view: dict | None,
    social_context: dict | None,
) -> None:
    if not isinstance(semantic_context, dict):
        return

    focus = list(semantic_context.get("decision_focus") or [])
    focus.extend(assess_needs(semantic_context, memory_context).focus_lines)
    focus.extend(exploration_proposal_lines(place_memory_context))
    focus.extend(social_proposal_lines(world_view, social_context))
    semantic_context["decision_focus"] = _dedupe(focus)


def _dedupe(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out
