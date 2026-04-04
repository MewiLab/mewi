"""
graph.py — LangGraph definition for the creature agent.

Design decisions:
- The graph does NOT own the agent.  It receives a CreatureAgent reference
  and calls its coordination API.  This means:
    * The same agent can be driven by different graphs (reactive, planning)
    * The graph can be tested with a mock agent
    * The agent can be used without a graph (e.g., scripted behavior)

- Each node is a plain function that takes state and returns a partial
  state update.  Nodes are thin — they call agent methods and format
  the results into state channels.  No business logic in nodes.

- The graph is built by a factory function (build_creature_graph) that
  takes a CreatureAgent.  The agent is captured in closures, not stored
  in state (state must be serializable; the agent is not).

- The reason node is where the LLM lives.  It's the only node that
  calls an LLM.  Every other node is deterministic.  This makes the
  system debuggable: if the agent does something wrong, you check the
  reason node's output, not the entire pipeline.

- Conditional edges handle two branch points:
    * After perceive: did perception succeed or fail?
    * After reason: did the LLM choose an action or decide to wait?
"""

import logging
from typing import Any, Literal, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from app.agent.schemas.state import AgentGraphState
from app.agent.agent import CreatureAgent
from app.agent.perception import PerceptionSummary, PerceptionError
from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ─── Node definitions ────────────────────────────────────────────────────────
# Each function returns a factory that closes over the agent instance.
# This keeps nodes testable (pass a mock agent) and stateless (no globals).


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


def make_reason_node(agent: CreatureAgent, model: Optional[ChatOpenAI] = None):
    """
    The LLM decision node — the only node that calls an LLM.

    Reads perception + memory, produces a chosen_action.
    """
    if model is None:
        settings = get_settings()
        model = ChatOpenAI(
            api_key=settings.openai_api_key,
            model="gpt-4.1",
            temperature=0,
        )

    def reason(state: AgentGraphState) -> dict[str, Any]:
        perception = state.get("perception", {})
        memory_ctx = state.get("memory_context", {})
        actions = state.get("available_actions", [])

        system_prompt = (
            "You are the brain of a cat navigating a 3D environment. "
            "Based on what you perceive and remember, choose ONE action to take. "
            "Respond with JSON only: {\"action\": \"<name>\", \"kwargs\": {}, \"reasoning\": \"<why>\"}\n\n"
            f"Available actions: {actions}\n"
        )

        user_content = (
            f"Current perception:\n{perception}\n\n"
            f"Recent memory:\n{memory_ctx}\n"
        )

        response = model.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        # Parse the LLM's response
        try:
            import json
            text = response.content.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            decision = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            logger.warning("LLM returned unparseable response: %s", response.content)
            decision = {"action": "wait", "kwargs": {}, "reasoning": "Failed to parse LLM output"}

        return {
            "chosen_action": {
                "action": decision.get("action", "wait"),
                "kwargs": decision.get("kwargs", {}),
            },
            "reasoning": decision.get("reasoning", ""),
            "messages": [
                HumanMessage(content=user_content),
                response,
            ],
        }

    return reason


def make_act_node(agent: CreatureAgent):
    """Execute the chosen action through the body."""

    async def act(state: AgentGraphState) -> dict[str, Any]:
        chosen = state.get("chosen_action")

        if not chosen or chosen.get("action") == "wait":
            return {
                "action_result": {"success": True, "action": "wait", "detail": "Intentional pause"},
            }

        result = await agent.act(chosen["action"], **chosen.get("kwargs", {}))

        return {
            "action_result": {
                "success": result.success,
                "action": result.action,
                "detail": result.detail,
            },
        }

    return act


def make_reflect_node(agent: CreatureAgent):
    """Post-action reflection — assess outcome, update memory annotations."""

    def reflect(state: AgentGraphState) -> dict[str, Any]:
        action_result = state.get("action_result", {})
        reasoning = state.get("reasoning", "")

        summary = (
            f"Action: {action_result.get('action', '?')} | "
            f"Success: {action_result.get('success', '?')} | "
            f"Reason: {reasoning}"
        )

        logger.info("Reflect: %s", summary)

        # If the action discovered something, annotate location
        # (future: more sophisticated reflection logic)

        return {
            "messages": [HumanMessage(content=f"[Reflection] {summary}")],
        }

    return reflect


# ─── Routing functions ───────────────────────────────────────────────────────

def route_after_perceive(state: AgentGraphState) -> Literal["remember", "act"]:
    """If perception failed, skip reasoning and just wait."""
    if state.get("perception_error"):
        return "act"  # act node will see no chosen_action and emit "wait"
    return "remember"


def route_after_reason(state: AgentGraphState) -> Literal["act", "__end__"]:
    """If the LLM chose 'wait', we can skip execution."""
    chosen = state.get("chosen_action", {})
    if chosen.get("action") == "wait":
        return END
    return "act"


# ─── Graph factory ───────────────────────────────────────────────────────────

def build_creature_graph(
    agent: CreatureAgent,
    model: Optional[ChatOpenAI] = None,
) -> StateGraph:
    """
    Build the LangGraph for one tick of creature behavior.

    The graph is:
        perceive → remember → reason → act → reflect
    
    With conditional branches:
        perceive --[error]--> act (wait)
        reason --[wait]--> END

    The agent is NOT stored in graph state.  It's captured by closures
    in the node functions.  Graph state is purely data (serializable).
    """

    graph = StateGraph(AgentGraphState)

    # Add nodes (each factory closes over the agent)
    graph.add_node("perceive", make_perceive_node(agent))
    graph.add_node("remember", make_remember_node(agent))
    graph.add_node("reason", make_reason_node(agent, model))
    graph.add_node("act", make_act_node(agent))
    graph.add_node("reflect", make_reflect_node(agent))

    # Edges
    graph.set_entry_point("perceive")
    graph.add_conditional_edges("perceive", route_after_perceive)
    graph.add_edge("remember", "reason")
    graph.add_conditional_edges("reason", route_after_reason)
    graph.add_edge("act", "reflect")
    graph.add_edge("reflect", END)

    return graph
