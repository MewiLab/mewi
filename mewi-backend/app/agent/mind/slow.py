from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.llm_provider import LLMProvider
from app.agent.mind.context import (
    clean_text,
    normalize_plan_steps,
    normalize_target,
    parse_llm_json_object,
)
from app.agent.mind.intents import INTENT_IDLE, INTENT_LEGACY_PLAN, normalize_intent
from app.agent.mind.prompt_builder import build_slow_mind_prompt_parts


__all__ = [
    "build_slow_mind_message",
    "make_slow_mind",
    "parse_intent_decision",
]


def _runtime(state: CreatureRuntimeState) -> CreatureRuntime:
    return state["runtime"]


def make_slow_mind(llm: LLMProvider):
    async def slow_mind(state: CreatureRuntimeState) -> dict[str, Any]:
        static_text, dynamic_text = build_slow_mind_prompt_parts(state, _runtime(state))
        message = build_slow_mind_message(llm, static_text, dynamic_text)
        response = await llm.ainvoke([message])
        decision = parse_intent_decision(str(response.content))
        return {
            "intent_decision": decision,
            "reasoning": decision["reasoning"],
            "messages": [message, response],
        }

    return slow_mind


def build_slow_mind_message(
    llm: LLMProvider,
    static_text: str,
    dynamic_text: str,
) -> HumanMessage:
    if _supports_anthropic_cache_control(llm):
        return HumanMessage(content=[
            {
                "type": "text",
                "text": static_text,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": dynamic_text},
        ])
    return HumanMessage(content=static_text + dynamic_text)


def parse_intent_decision(content: str) -> dict[str, Any]:
    data = parse_llm_json_object(content)
    if not data:
        data = {
            "intent": INTENT_IDLE,
            "reasoning": "Failed to parse LLM intent output.",
        }

    suggested_plan_steps = normalize_plan_steps(data.get("plan_steps"))
    intent = normalize_intent(data.get("intent"), default="")
    if not intent:
        intent = INTENT_LEGACY_PLAN if suggested_plan_steps else INTENT_IDLE

    return {
        "intent": intent,
        "target_id": normalize_target(data.get("target_id", data.get("target"))) or "",
        "mood": clean_text(data.get("mood")),
        "style": (
            clean_text(data.get("style"))
            or clean_text(data.get("action_style"))
            or clean_text(data.get("persona_style"))
        ),
        "reasoning": (
            clean_text(data.get("reasoning"))
            or clean_text(data.get("thought"))
            or "No slow-mind reasoning returned."
        ),
        "suggested_plan_steps": suggested_plan_steps,
    }


def _supports_anthropic_cache_control(llm: Any) -> bool:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return False
    return isinstance(llm, ChatAnthropic)
