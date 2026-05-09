import json
import logging
from typing import Any, Literal

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from app.agent.schemas.state_schema import AgentGraphState
from app.agent.creature_agent import CreatureAgent
from app.agent.schemas.perception_schema import PerceptionError
from app.agent.llm_provider import LLMProvider
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


def make_reason_node(agent: CreatureAgent, llm: LLMProvider):
    """
    The LLM decision node — the only node that calls an LLM.
    Receives an LLMProvider — doesn't know or care which backend it is.
    Reads perception + memory, produces a chosen_action.
    """

    def _intensity(v: float) -> str:
        return "HIGH" if v >= 0.7 else "low" if v <= 0.3 else "moderate"

    def _fmt_mood(mood: dict) -> str:
        keys = ("fear", "trust", "curiosity", "social", "energy")
        return "\n".join(
            f"  {k:<10} {mood.get(k, 0.0):.2f}  [{_intensity(mood.get(k, 0.0))}]"
            for k in keys
        )

    def _fmt_entities(entities: list) -> str:
        if not entities:
            return "  (none visible)"
        lines = []
        for e in entities:
            tags = ", ".join(e.get("tags") or []) or "unknown"
            lines.append(
                f"  • {e.get('id', '?'):20s}  tags=[{tags}]"
                f"  dist={e.get('distance', '?')}m  dir={e.get('direction', '?')}"
            )
        return "\n".join(lines)

    async def reason(state: AgentGraphState) -> dict[str, Any]:
        raw        = state.get("raw_payload", {})
        memory_ctx = state.get("memory_context", {})
        actions    = state.get("available_actions", []) or ["move", "stop", "wait"]

        # Pull the rich sensor fields that SnapshotManager cannot see
        # (it expects environment_snapshot/creature_snapshot keys; Unity sends
        # self/mood/health/entities).  Reading raw_payload bypasses that mismatch.
        mood      = raw.get("mood", {})
        health    = raw.get("health", {})
        self_st   = raw.get("self", {})
        loc       = self_st.get("location", {})
        entities  = raw.get("entities", [])

        system_prompt = (
            "You are the brain of a cat navigating a 3D environment.\n"
            "Your decisions MUST be driven by your current mood and what you sense nearby.\n"
            "High fear → avoid or hide. High curiosity → approach. Low energy → rest.\n"
            "Entities that are close (<3 m) and approaching demand an immediate response.\n\n"
            "Respond with ONLY a JSON object — no extra text:\n"
            '  {"action": "<name>", "kwargs": {}, "reasoning": "<why>"}\n\n'
            f"Available actions: {actions}\n\n"
            "For 'move': kwargs = "
            '{"x": <-1..1 left/right>, "y": <-1..1 back/fwd>, "hold": <seconds>}\n'
            "For button actions (Sprint, Jump …): kwargs may include hold: float.\n"
        )

        user_content = (
            "=== Position ===\n"
            f"  x={loc.get('x', 0.0):.2f}  y={loc.get('y', 0.0):.2f}  z={loc.get('z', 0.0):.2f}\n"
            f"  current_action: {self_st.get('current_action', 'idle')}\n\n"
            "=== Mood ===\n"
            f"{_fmt_mood(mood)}\n\n"
            "=== Health ===\n"
            f"  hunger     {health.get('hunger', 0.0):.2f}  [{_intensity(health.get('hunger', 0.0))}]\n\n"
            "=== Nearby entities ===\n"
            f"{_fmt_entities(entities)}\n\n"
            "=== Recent memory ===\n"
            f"{memory_ctx}\n"
        )

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        try:
            text = response.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            decision = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            logger.warning("LLM returned unparseable response: %s", response.content)
            decision = {
                "action": "wait", "kwargs": {}, 
                "reasoning": "Failed to parse LLM output"
            }

        return {
            "chosen_action": {
                "action": decision.get("action", "wait"), 
                "kwargs": decision.get("kwargs", {})
            },
            "reasoning": decision.get("reasoning", ""),
            "messages": [HumanMessage(content=user_content), response],
        }
    return reason


def make_act_node(agent: CreatureAgent):
    """Execute the chosen action through the body."""

    async def act(state: AgentGraphState) -> dict[str, Any]:
        chosen = state.get("chosen_action")

        if not chosen or chosen.get("action") == "wait":
            return {
                "action_result": {
                    "success": True, 
                    "action": "wait", 
                    "detail": "Intentional pause"
                },
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


def route_after_perceive(state: AgentGraphState) -> Literal["remember", "act"]:
    """If perception failed, skip reasoning and just wait."""
    return "act" if state.get("perception_error") else "remember"  # act node will see no chosen_action and emit "wait"

def route_after_reason(state: AgentGraphState) -> Literal["act", "__end__"]:
    """If the LLM chose 'wait', we can skip execution."""
    return END if state.get("chosen_action", {}).get("action") == "wait" else "act"


def build_creature_graph(
    agent: CreatureAgent,
    llm: LLMProvider, 
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
    graph.add_node("reason"  , make_reason_node(agent, llm))
    graph.add_node("act"     , make_act_node(agent))
    graph.add_node("reflect" , make_reflect_node(agent))

    graph.set_entry_point("perceive")
    graph.add_conditional_edges("perceive", route_after_perceive)
    graph.add_edge("remember", "reason")
    graph.add_conditional_edges("reason", route_after_reason)
    graph.add_edge("act", "reflect")
    graph.add_edge("reflect", END)

    return graph
