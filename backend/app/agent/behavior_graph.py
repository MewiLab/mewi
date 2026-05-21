import json
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.llm_provider import LLMProvider
from app.agent.prompts import format_strategic_prompt
from app.agent.schemas.perception_schema import PerceptionError
from app.services.semantic_service import SemanticService


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
        semantic_context = SemanticService().build_prompt_context(raw)
        prompt = format_strategic_prompt(
            temperament="curious",
            trust="unknown",
            position="",
            current_action="",
            mood={},
            health={},
            entities=[],
            actions=state.get("actions_for_prompt")
            or _runtime(state).action_prompt_descriptions,
            feelings={},
            semantic_context=semantic_context,
            persona=state.get("persona") or _runtime(state).persona,
            previous_action_result=_format_previous_action_result(raw.get("action_result")),
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        decision = _parse_decision(str(response.content))
        action_result = _runtime(state).action_result(
            decision["chosen_action"]["action"],
            decision["chosen_action"].get("kwargs"),
        )
        return {
            "chosen_action": decision["chosen_action"],
            "plan_steps": decision["plan_steps"],
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

    plan_steps = _normalize_plan_steps(data.get("plan_steps"))
    action = (
        (plan_steps[0]["action"] if plan_steps else "")
        or _normalize_action(data.get("final_action"))
        or _normalize_action(data.get("action"))
        or "idle"
    )
    kwargs = data.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        kwargs = {}
    if "target" in kwargs:
        normalized_target = _normalize_target(kwargs.get("target"))
        if normalized_target is None:
            kwargs.pop("target", None)
        else:
            kwargs["target"] = normalized_target
    target = plan_steps[0].get("target") if plan_steps else None
    if target is None:
        target = _normalize_target(data.get("target_id"))
    if target is not None and "target" not in kwargs:
        kwargs["target"] = target
    return {
        "chosen_action": {"action": action, "kwargs": kwargs},
        "plan_steps": plan_steps,
        "reasoning": data.get("reasoning") or data.get("thought") or "",
    }


def _normalize_plan_steps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    steps: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action = _normalize_action(item.get("action"))
        if not action:
            continue
        steps.append({
            "action": action,
            "target": _normalize_target(item.get("target", item.get("target_id"))),
            "reason": _clean_text(item.get("reason")),
        })
    return steps


def _normalize_action(value: Any) -> str:
    text = _clean_text(value)
    if not text or text.lower() in {
        "action_name",
        "action_id",
        "immediate action_id to execute",
    }:
        return ""
    return text


def _normalize_target(value: Any) -> str | None:
    text = _clean_text(value)
    if not text or text.lower() in {
        "null",
        "none",
        "entity_id",
        "entity_id_or_null",
        "specific entity id, or null",
    }:
        return None
    return text


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def _format_previous_action_result(value: Any) -> str:
    if not isinstance(value, dict):
        return ""

    status = _clean_text(value.get("status")) or "unknown"
    lines = [_status_sentence(status)]

    steps = value.get("steps")
    if not isinstance(steps, list) or not steps:
        return "\n".join(f"  - {line}" for line in lines)

    for step in steps[:6]:
        if not isinstance(step, dict):
            continue
        action = _clean_text(step.get("action")) or "unknown"
        step_status = _clean_text(step.get("status")) or "unknown"
        target = _clean_text(step.get("target"))
        reason = _clean_text(step.get("reason"))
        lines.append(_step_feedback(action, step_status, target, reason))
    return "\n".join(f"  - {line}" for line in lines)


def _status_sentence(status: str) -> str:
    if status == "completed":
        return "The previous plan completed."
    if status == "completed_with_rejections":
        return "The previous plan partly worked, but at least one step was rejected."
    if status in {"failed", "rejected"}:
        return "The previous plan did not work; choose a different small action."
    return f"The previous plan status was {status.replace('_', ' ')}."


def _step_feedback(action: str, status: str, target: str, reason: str) -> str:
    target_text = f" on {target}" if target else ""
    if status == "completed":
        return f"{action}{target_text} worked."
    if status == "rejected":
        if "unmapped_action" in reason:
            return f"Avoid {action} for now; Unity rejected it as unmapped."
        return f"{action}{target_text} was rejected."
    if status == "failed":
        return f"{action}{target_text} failed."
    return f"{action}{target_text} ended as {status.replace('_', ' ')}."


def _format_location(location: Any) -> str:
    if isinstance(location, dict):
        return ", ".join(f"{key}={float(location.get(key, 0.0) or 0.0):.2f}" for key in ("x", "y", "z"))
    return str(location or "unknown")
