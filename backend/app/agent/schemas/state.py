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

from typing import TypedDict, Annotated, Any, Optional
import operator


class AgentGraphState(TypedDict):
    """
    State channels for the creature agent LangGraph.

    Flow:
      perceive → writes perception, raw_payload
      remember → writes memory_context
      reason   → reads perception + memory, writes chosen_action, messages
      act      → reads chosen_action, writes action_result
      reflect  → reads action_result, writes messages

    Each node only touches its own channels.  No node reaches into
    another node's concerns.
    """

    # ─── Perception channel (written by perceive node) ───────────────
    raw_payload: dict[str, Any]                  # Raw JSON from Unity
    perception: Optional[dict[str, Any]]         # PerceptionSummary.to_prompt_context()
    perception_error: Optional[str]              # Non-None if eye failed

    # ─── Memory channel (written by remember node) ───────────────────
    memory_context: Optional[dict[str, Any]]     # MemoryRecall.to_prompt_context()

    # ─── Reasoning channel (written by reason node) ──────────────────
    chosen_action: Optional[dict[str, Any]]      # {"action": "Jump", "kwargs": {"hold": 0.3}}
    reasoning: Optional[str]                     # LLM's chain-of-thought (for debugging)

    # ─── Action channel (written by act node) ────────────────────────
    action_result: Optional[dict[str, Any]]      # {"success": bool, "action": str, "detail": str}

    # ─── Message history (appended by reason + reflect nodes) ────────
    messages: Annotated[list, operator.add]

    # ─── Metadata ────────────────────────────────────────────────────
    tick: int
    available_actions: list[str]
