from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.llm_provider import LLMProvider
from app.agent.mind.context import (
    clean_text,
    normalize_action,
    normalize_plan_steps,
    normalize_target,
    parse_llm_json_object,
)
from app.agent.mind.intents import (
    INTENT_EXPLORE,
    INTENT_IDLE,
    INTENT_INVESTIGATE,
    INTENT_LEGACY_PLAN,
    INTENT_REST,
    INTENT_SAFETY,
    INTENT_SEEK_FOOD,
    INTENT_SEEK_PLAYER,
    INTENT_SOCIALIZE,
    KNOWN_INTENTS,
    normalize_intent,
)
from app.agent.mind.prompt_builder import build_fast_mind_prompt


MAX_PLAN_STEPS = 8

__all__ = [
    "INTENT_EXPLORE",
    "INTENT_IDLE",
    "INTENT_INVESTIGATE",
    "INTENT_LEGACY_PLAN",
    "INTENT_REST",
    "INTENT_SAFETY",
    "INTENT_SEEK_FOOD",
    "INTENT_SEEK_PLAYER",
    "INTENT_SOCIALIZE",
    "KNOWN_INTENTS",
    "MAX_PLAN_STEPS",
    "chosen_action_from_plan",
    "fast_mind_reasoning",
    "make_fast_mind",
    "normalize_intent",
    "parse_fast_mind_response",
]


def _runtime(state: CreatureRuntimeState) -> CreatureRuntime:
    return state["runtime"]


def make_fast_mind(llm: LLMProvider):
    async def fast_mind(state: CreatureRuntimeState) -> dict[str, Any]:
        runtime = _runtime(state)
        prompt = build_fast_mind_prompt(
            state,
            runtime,
            max_plan_steps=MAX_PLAN_STEPS,
        )
        message = HumanMessage(content=prompt)
        response = await llm.ainvoke([message])
        fast_result = parse_fast_mind_response(
            str(response.content),
            available_actions=runtime.available_actions,
        )
        plan_steps = fast_result["plan_steps"] or [_fallback_step(runtime.available_actions)]
        chosen_action = chosen_action_from_plan(plan_steps)
        action_result = runtime.action_result(
            chosen_action["action"],
            chosen_action.get("kwargs"),
        )
        reasoning = fast_mind_reasoning(
            state.get("intent_decision"),
            plan_steps,
            fast_result.get("reasoning", ""),
        )
        return {
            "chosen_action": chosen_action,
            "plan_steps": plan_steps,
            "action_result": action_result.model_dump(),
            "reasoning": reasoning,
            "messages": [message, response],
        }

    return fast_mind


def parse_fast_mind_response(
    content: str,
    *,
    available_actions: list[str],
    max_steps: int = MAX_PLAN_STEPS,
) -> dict[str, Any]:
    data = parse_llm_json_object(content)
    if not data:
        return {
            "plan_steps": [],
            "reasoning": "Failed to parse Fast Mind output.",
        }

    return {
        "plan_steps": normalize_plan_steps(
            data.get("plan_steps"),
            available_actions=available_actions,
            max_steps=max_steps,
        ),
        "reasoning": clean_text(data.get("reasoning")) or "Fast Mind returned an action plan.",
    }


def chosen_action_from_plan(plan_steps: list[dict[str, Any]]) -> dict[str, Any]:
    first = plan_steps[0] if plan_steps else {"action": "idle", "target": None}
    action = normalize_action(first.get("action")) or "idle"
    target = normalize_target(first.get("target"))
    kwargs: dict[str, Any] = {}
    if target is not None:
        kwargs["target"] = target
    return {"action": action, "kwargs": kwargs}


def fast_mind_reasoning(
    intent_decision: dict[str, Any] | None,
    plan_steps: list[dict[str, Any]],
    fast_reasoning: str = "",
) -> str:
    decision = intent_decision if isinstance(intent_decision, dict) else {}
    intent = clean_text(decision.get("intent")) or INTENT_IDLE
    slow_reason = clean_text(decision.get("reasoning"))
    style = clean_text(decision.get("style"))
    plan_text = _plan_text(plan_steps)

    parts: list[str] = []
    if slow_reason:
        parts.append(slow_reason)
    if fast_reasoning:
        parts.append(fast_reasoning)

    style_text = f" with a {style} style" if style else ""
    parts.append(f"Fast Mind translated {intent}{style_text} into {plan_text}.")
    return " ".join(parts)


def _fallback_step(available_actions: list[str]) -> dict[str, Any]:
    available = [
        clean_text(action).split(":", 1)[0].strip()
        for action in available_actions
        if clean_text(action)
    ]
    action = "idle" if "idle" in available else (available[0] if available else "idle")
    return {
        "action": action,
        "target": None,
        "reason": "fallback after unreadable fast-mind output",
    }


def _plan_text(plan_steps: list[dict[str, Any]]) -> str:
    if not plan_steps:
        return "idle"
    return " -> ".join(
        f"{step.get('action')}{(':' + step.get('target')) if step.get('target') else ''}"
        for step in plan_steps
    )
