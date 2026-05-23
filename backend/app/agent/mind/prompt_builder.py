from __future__ import annotations

from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.mind.context import format_previous_action_result
from app.agent.prompts import format_slow_mind_prompt_parts
from app.agent.prompts.fast_mind import format_fast_mind_prompt
from app.services.semantic_service import SemanticService


__all__ = ["build_fast_mind_prompt", "build_slow_mind_prompt_parts"]


def build_slow_mind_prompt_parts(
    state: CreatureRuntimeState,
    runtime: CreatureRuntime,
) -> tuple[str, str]:
    raw = state.get("raw_payload", {})
    semantic_context = SemanticService().build_prompt_context(raw)
    return format_slow_mind_prompt_parts(
        temperament="curious",
        trust="unknown",
        actions=state.get("actions_for_prompt") or runtime.action_prompt_descriptions,
        semantic_context=semantic_context,
        place_memory_context=state.get("place_memory_context"),
        memory_context=state.get("memory_context"),
        world_view=state.get("world_view"),
        social_context=state.get("social_context"),
        persona=state.get("persona") or runtime.persona,
        previous_action_result=format_previous_action_result(raw.get("action_result")),
    )


def build_fast_mind_prompt(
    state: CreatureRuntimeState,
    runtime: CreatureRuntime,
    *,
    max_plan_steps: int,
) -> str:
    raw = state.get("raw_payload", {})
    semantic_context = SemanticService().build_prompt_context(raw)
    return format_fast_mind_prompt(
        intent_decision=state.get("intent_decision"),
        actions=state.get("actions_for_prompt") or runtime.action_prompt_descriptions,
        semantic_context=semantic_context,
        place_memory_context=state.get("place_memory_context"),
        memory_context=state.get("memory_context"),
        world_view=state.get("world_view"),
        social_context=state.get("social_context"),
        previous_action_result=format_previous_action_result(raw.get("action_result")),
        max_plan_steps=max_plan_steps,
    )
