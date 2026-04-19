"""
graph.py — LangGraph wiring for the MEW creature agent.

Nodes are thin: each delegates real work to either the CreatureAgent
(perception, memory, action) or the LLMProvider (reasoning).
All prompt content lives in prompts.py.
"""

import json
import logging
import re
from typing import Any, Literal

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from app.agent.schemas.state_schema import AgentGraphState
from app.agent.creature_agent import CreatureAgent
from app.agent.schemas.perception_schema import PerceptionError
from app.agent.llm_provider import LLMProvider
from app.agent.prompts import (
    build_mew_system_prompt,
    format_perception_for_prompt,
    format_memory_for_prompt,
)

logger = logging.getLogger(__name__)

# Regex to strip markdown code fences the LLM sometimes wraps JSON in.
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```")


# ─── JSON extraction helper ──────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Parse LLM output into a dict as robustly as possible.

    Handles:
    - Clean JSON
    - JSON wrapped in ```json ... ``` or ``` ... ``` fences
    - JSON embedded somewhere in a longer text response
    """
    text = text.strip()

    # 1. Try clean parse first (fastest path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    match = _FENCE_RE.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Find the first {...} block anywhere in the text
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in LLM response: {text[:200]}")


# ─── Node factories ──────────────────────────────────────────────────────────

def make_perceive_node(agent: CreatureAgent):
    """Process raw Unity payload through the eye."""

    def perceive(state: AgentGraphState) -> dict[str, Any]:
        raw = state["raw_payload"]
        result = agent.perceive(raw)

        if isinstance(result, PerceptionError):
            return {
                "perception": None,
                "perception_error": result.message,
            }

        return {
            "perception": result.to_prompt_context(),
            "perception_error": None,
            "tick": result.tick,
        }

    return perceive


def make_remember_node(agent: CreatureAgent):
    """Retrieve recent memory for context."""

    def remember(state: AgentGraphState) -> dict[str, Any]:
        recall = agent.remember(last_n=5)
        return {
            "memory_context": recall.to_prompt_context(),
        }

    return remember


def make_reason_node(agent: CreatureAgent, llm: LLMProvider):
    """
    The LLM decision node — the only node that calls an external model.

    Reads: perception, memory_context, goal, internal_state, available_actions
    Writes: chosen_action, reasoning, messages
    """

    async def reason(state: AgentGraphState) -> dict[str, Any]:
        perception    = state.get("perception") or {}
        memory_ctx    = state.get("memory_context") or {}
        goal          = state.get("goal") or "Explore and stay safe."
        internal_state = state.get("internal_state") or {}

        perception_text = format_perception_for_prompt(perception)
        memory_text     = format_memory_for_prompt(memory_ctx)
        action_desc     = agent.body.get_actions_for_prompt()

        system_prompt = build_mew_system_prompt(
            action_desc=action_desc,
            goal=goal,
            internal_state=internal_state,
        )
        user_content = (
            f"=== Current Perception ===\n{perception_text}\n\n"
            f"=== Recent Memory ===\n{memory_text}"
        )

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        try:
            decision = _extract_json(response.content)
        except (ValueError, AttributeError):
            logger.warning(
                "LLM returned unparseable response (tick=%d): %.300s",
                state.get("tick", 0),
                getattr(response, "content", ""),
            )
            decision = {
                "action": "wait",
                "kwargs": {},
                "reasoning": "Failed to parse LLM output — defaulting to wait.",
            }

        return {
            "chosen_action": {
                "action": decision.get("action", "wait"),
                "kwargs": decision.get("kwargs") or {},
            },
            "reasoning": decision.get("reasoning", ""),
            "messages": [HumanMessage(content=user_content), response],
        }

    return reason


def make_act_node(agent: CreatureAgent):
    """
    Capture the chosen action for delivery via Redis polling.

    The action is not sent directly to Unity here — the worker writes
    it to Redis and Unity polls for it.
    """

    def act(state: AgentGraphState) -> dict[str, Any]:
        chosen = state.get("chosen_action")

        if not chosen or chosen.get("action") == "wait":
            return {"action_result": {"action": "wait", "kwargs": {}}}

        return {
            "action_result": {
                "action": chosen["action"],
                "kwargs": chosen.get("kwargs") or {},
            },
        }

    return act


def make_reflect_node(agent: CreatureAgent):
    """Post-action reflection — assess outcome and update memory annotations."""

    def reflect(state: AgentGraphState) -> dict[str, Any]:
        action_result = state.get("action_result") or {}
        reasoning     = state.get("reasoning") or ""

        summary = (
            f"Action: {action_result.get('action', '?')} | "
            f"Reason: {reasoning[:120]}"
        )
        logger.info("Reflect: %s", summary)

        return {
            "messages": [HumanMessage(content=f"[Reflection] {summary}")],
        }

    return reflect


# ─── Routing ─────────────────────────────────────────────────────────────────

def route_after_perceive(state: AgentGraphState) -> Literal["remember", "act"]:
    """Skip reasoning when perception failed — act node will emit 'wait'."""
    return "act" if state.get("perception_error") else "remember"


def route_after_reason(state: AgentGraphState) -> Literal["act"]:
    """Always pass through act so reflect always runs regardless of action."""
    return "act"


# ─── Graph builder ────────────────────────────────────────────────────────────

def build_creature_graph(
    agent: CreatureAgent,
    llm: LLMProvider,
) -> StateGraph:
    """
    Build the LangGraph for one tick of creature behavior:

        perceive → remember → reason → act → reflect → END
                 ↘ (error) ↗

    The agent is NOT stored in graph state.  It's captured by closures
    in the node functions so state is purely serializable data.
    """
    graph = StateGraph(AgentGraphState)
    graph.add_node("perceive", make_perceive_node(agent))
    graph.add_node("remember", make_remember_node(agent))
    graph.add_node("reason",   make_reason_node(agent, llm))
    graph.add_node("act",      make_act_node(agent))
    graph.add_node("reflect",  make_reflect_node(agent))

    graph.set_entry_point("perceive")
    graph.add_conditional_edges("perceive", route_after_perceive)
    graph.add_edge("remember", "reason")
    graph.add_conditional_edges("reason", route_after_reason)
    graph.add_edge("act", "reflect")
    graph.add_edge("reflect", END)

    return graph
