from dataclasses import dataclass
from typing import Any

from app.agent.schemas.perception_schema import PerceptionSummary
from app.agent.schemas.memory_schema import MemoryRecall


# ─── Agent state snapshot (for graph consumption) ────────────────────────────

@dataclass
class AgentContext:
    """
    Everything the graph needs to make a decision, in one object.
    Built by agent.get_context() each tick.

    Why a dedicated type instead of passing eye/memory/body separately
    to each graph node?  Because the graph state must be serializable
    (LangGraph checkpoints it).  This is a clean serialization boundary.
    """
    perception: PerceptionSummary | None
    memory: MemoryRecall
    available_actions: list[str]
    tick: int
    is_connected: bool

    def to_prompt_context(self) -> dict[str, Any]:
        """Flatten into a dict the LLM can read in its context window."""
        ctx: dict[str, Any] = {
            "tick": self.tick,
            "connected": self.is_connected,
            "available_actions": self.available_actions,
        }
        if self.perception:
            ctx["perception"] = self.perception.to_prompt_context()
        ctx["memory"] = self.memory.to_prompt_context()
        return ctx