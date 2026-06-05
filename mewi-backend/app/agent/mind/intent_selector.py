from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.llm_provider import LLMProvider
from app.agent.mind.affordances import IntentAffordances, build_intent_affordances
from app.agent.mind.context import clean_text, normalize_target, parse_llm_json_object
from app.agent.mind.intents import INTENT_IDLE, normalize_intent
from app.agent.mind.prompt_builder import build_intent_selection_prompt_parts


__all__ = [
    "build_intent_selection_message",
    "make_intent_selector",
    "parse_intent_decision",
]


def _runtime(state: CreatureRuntimeState) -> CreatureRuntime:
    return state["runtime"]


def make_intent_selector(llm: LLMProvider):
    async def intent_selector(state: CreatureRuntimeState) -> dict[str, Any]:
        static_text, dynamic_text, affordances = build_intent_selection_prompt_parts(
            state,
            _runtime(state),
        )
        message = build_intent_selection_message(llm, static_text, dynamic_text)
        response = await llm.ainvoke([message])
        decision = parse_intent_decision(str(response.content), affordances=affordances)
        return {
            "intent_decision": decision,
            "intent_affordances": affordances.to_prompt_context(),
            "chosen_action": None,
            "plan_steps": [],
            "action_result": None,
            "reasoning": decision["reasoning"],
            "messages": [message, response],
        }

    return intent_selector


def build_intent_selection_message(
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


def parse_intent_decision(
    content: str,
    *,
    affordances: IntentAffordances | dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = parse_llm_json_object(content)
    if not data:
        data = {
            "intent": INTENT_IDLE,
            "reasoning": "Failed to parse intent selector output.",
        }

    parsed_affordances = _coerce_affordances(affordances)
    intent = normalize_intent(data.get("intent"), default=INTENT_IDLE)
    if not parsed_affordances.allows_intent(intent):
        intent = INTENT_IDLE

    target_id = normalize_target(data.get("target_id", data.get("target"))) or ""
    if target_id and not parsed_affordances.target_supports_intent(target_id, intent):
        target_id = ""

    return {
        "intent": intent,
        "target_id": target_id,
        "mood": clean_text(data.get("mood")),
        "style": (
            clean_text(data.get("style"))
            or clean_text(data.get("directive_style"))
            or clean_text(data.get("persona_style"))
        ),
        "reasoning": (
            clean_text(data.get("reasoning"))
            or clean_text(data.get("thought"))
            or "No intent-selector reasoning returned."
        ),
    }


def _coerce_affordances(value: IntentAffordances | dict[str, Any] | None) -> IntentAffordances:
    if isinstance(value, IntentAffordances):
        return value
    if isinstance(value, dict):
        return build_intent_affordances(value)
    return build_intent_affordances({})


def _supports_anthropic_cache_control(llm: Any) -> bool:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return False
    return isinstance(llm, ChatAnthropic)
