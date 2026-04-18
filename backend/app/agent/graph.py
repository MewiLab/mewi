import logging
from typing import Any, Literal

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from app.agent.schemas.state_schema import AgentGraphState
from app.agent.creature_agent import CreatureAgent
from app.agent.schemas.perception_schema import PerceptionError
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


def make_reason_node(agent: CreatureAgent, model: ChatOpenAI | None = None):
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
    """
    Capture the chosen action for delivery via Redis polling.

    The action is no longer sent directly to Unity here — the background
    worker (agent_tasks.py) writes it to Redis and Unity polls for it.
    """

    def act(state: AgentGraphState) -> dict[str, Any]:
        chosen = state.get("chosen_action")

        if not chosen or chosen.get("action") == "wait":
            return {
                "action_result": {"action": "wait", "kwargs": {}},
            }

        return {
            "action_result": {
                "action": chosen["action"],
                "kwargs": chosen.get("kwargs", {}),
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


def build_creature_graph(
    agent: CreatureAgent,
    model: ChatOpenAI | None = None,
) -> StateGraph:
    """
    Build the LangGraph for one tick of creature behavior.
    perceive -> remember -> reason -> act -> reflect
             -> act                -> end
    
    With conditional branches:
        perceive --[error]--> act (wait)
        reason --[wait]--> END

    The agent is NOT stored in graph state.  It's captured by closures
    in the node functions.  Graph state is purely data (serializable).
    """

    graph = StateGraph(AgentGraphState)

    graph.add_node("perceive", make_perceive_node(agent))
    graph.add_node("remember", make_remember_node(agent))
    graph.add_node("reason"  , make_reason_node(agent, model))
    graph.add_node("act"     , make_act_node(agent))
    graph.add_node("reflect" , make_reflect_node(agent))


    graph.set_entry_point("perceive")
    graph.add_conditional_edges("perceive", route_after_perceive)
    graph.add_edge("remember", "reason")
    graph.add_conditional_edges("reason", route_after_reason)
    graph.add_edge("act", "reflect")
    graph.add_edge("reflect", END)

    return graph
