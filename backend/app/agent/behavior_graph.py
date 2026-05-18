import json
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.llm_provider import LLMProvider
from app.agent.prompts import format_strategic_prompt
from app.agent.schemas.perception_schema import PerceptionError


def _runtime(state: CreatureRuntimeState) -> CreatureRuntime:
    return state["runtime"]


def perceive(state: CreatureRuntimeState) -> dict[str, Any]:
    result = _runtime(state).perceive(state["raw_payload"])
    if isinstance(result, PerceptionError):
        return {"perception": None, "perception_error": result.message}
    return {
        "perception": result.to_prompt_context(),
        "perception_error": None,
        "tick": result.tick,
    }


def remember(state: CreatureRuntimeState) -> dict[str, Any]:
    return {"memory_context": _runtime(state).remember(last_n=5).to_prompt_context()}


def make_reason(llm: LLMProvider):
    async def reason(state: CreatureRuntimeState) -> dict[str, Any]:
        raw = state.get("raw_payload", {})
        self_state = raw.get("self", {})
        prompt = format_strategic_prompt(
            temperament="curious",
            trust="unknown",
            position=_format_position(
                self_state.get("location", ""),
                raw.get("spatial_context", {}),
            ),
            current_action=self_state.get("current_action", "idle"),
            mood=raw.get("mood", {}),
            health=raw.get("health", {}),
            entities=raw.get("entities", []),
            actions=state.get("actions_for_prompt")
            or _runtime(state).action_prompt_descriptions,
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        decision = _parse_decision(str(response.content))
        action_result = _runtime(state).action_result(
            decision["chosen_action"]["action"]
        )
        return {
            "chosen_action": decision["chosen_action"],
            "action_result": action_result.model_dump(),
            "reasoning": decision["reasoning"],
            "messages": [HumanMessage(content=prompt), response],
        }

    return reason


def build_behavior_graph(llm: LLMProvider) -> StateGraph:
    graph = StateGraph(CreatureRuntimeState)
    graph.add_node("perceive", perceive)
    graph.add_node("remember", remember)
    graph.add_node("reason", make_reason(llm))
    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "remember")
    graph.add_edge("remember", "reason")
    graph.add_edge("reason", END)
    return graph


def _parse_decision(content: str) -> dict[str, Any]:
    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        data = {"final_action": "idle", "reasoning": "Failed to parse LLM output"}

    action = data.get("action") or data.get("final_action") or "idle"
    kwargs = data.get("kwargs") or {}
    if data.get("target_id") and "target" not in kwargs:
        kwargs["target"] = data["target_id"]
    return {
        "chosen_action": {"action": action, "kwargs": kwargs},
        "reasoning": data.get("reasoning") or data.get("thought") or "",
    }


def _format_position(location: Any, spatial_context: dict[str, Any]) -> str:
    location_text = _format_location(location)
    zones = spatial_context.get("zones") or []
    zone_text = ", ".join(
        f"{zone.get('id', 'unknown')}({zone.get('type', 'zone')})"
        for zone in zones
    )
    if zone_text:
        return f"{location_text}; nearby zones: {zone_text}"
    return location_text


def _format_location(location: Any) -> str:
    if isinstance(location, dict):
        return ", ".join(f"{key}={float(location.get(key, 0.0) or 0.0):.2f}" for key in ("x", "y", "z"))
    return str(location or "unknown")
