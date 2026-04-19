"""
state.py — LangGraph state definition for the creature agent graph.

Design decisions:
- AgentGraphState is a TypedDict, not a Pydantic model, because LangGraph
  uses TypedDict for its state channels.  Each field is a channel that
  graph nodes can read and write.

- The state carries the agent context (perception + memory + available
  actions), the LLM's reasoning output, and the action result.  Each
  graph node reads what it needs and writes what it produces.

- Messages use the LangGraph Annotated[list, operator.add] pattern so
  that each node appends to the message history instead of replacing it.
  This gives the LLM the full conversation context.

- The chosen_action field is a dict (not an ActionResult) because the
  reasoning node produces it before execution.  The action node executes
  it and writes the result.
"""

from typing import TypedDict, Annotated, Any
import operator


class AgentGraphState(TypedDict):
    """
    State channels for the creature agent LangGraph.

    Flow:
      perceive → writes perception, raw_payload
      remember → writes memory_context
      reason   → reads perception + memory + goal + internal_state,
                 writes chosen_action, messages
      act      → reads chosen_action, writes action_result
      reflect  → reads action_result, writes messages

    Each node only touches its own channels.  No node reaches into
    another node's concerns.
    """

    # Perception
    raw_payload: dict[str, Any]               # Raw JSON from Unity
    perception: dict[str, Any] | None         # PerceptionSummary.to_prompt_context()
    perception_error: str | None              # Non-None if eye failed

    # Memory
    memory_context: dict[str, Any] | None     # MemoryRecall.to_prompt_context()

    # Reasoning
    chosen_action: dict[str, Any] | None      # {"action": "Jump", "kwargs": {"hold": 0.3}}
    reasoning: str | None                     # LLM's chain-of-thought (for debugging)

    # Action
    action_result: dict[str, Any] | None      # {"action": str, "kwargs": dict}

    # Message history (appended by reason + reflect)
    messages: Annotated[list, operator.add]

    # Metadata
    tick: int
    available_actions: list[str]

    # Agent intent & internal state — inform the LLM's instinct-driven decisions
    goal: str | None                          # Current high-level objective
    internal_state: dict[str, Any] | None     # {"energy": float, "hunger": float, "mood": str}
