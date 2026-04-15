"""
The DI container that wires Eye, Memory, Body.

Design decisions:
- The agent is NOT the brain.  It's the creature — a body with senses
  and memory.  The brain is the LangGraph that operates on it from outside.
  This separation means you can swap the graph (reactive, planning,
  hardcoded) without touching the creature.

- All three subsystems are injected via constructor.  Tests create a
  CreatureAgent with mock subsystems.  Production creates one with real
  ones.  The agent class itself has zero knowledge of HTTP, Unity, or LLMs.

- The agent exposes a small coordination API (perceive, remember, act)
  that the graph nodes call.  These methods compose the subsystems but
  add no logic of their own — they're glue, not brains.

- A factory function (create_creature_agent) handles production wiring.
  This is what FastAPI's dependency injection calls.  The constructor
  stays clean and test-friendly.
"""
from __future__ import annotations
import logging
from typing import Any

from app.agent.schemas.context_schema import AgentContext
from app.agent.schemas.perception_schema import PerceptionSummary, PerceptionError
from app.agent.perception import SnapshotManager
from app.agent.memory import MemoryManager, MemoryRecall
from app.agent.action import ActionManager, ActionResult

logger = logging.getLogger(__name__)


class CreatureAgent:
    """
    A creature with an eye, memory, and body.
    The LangGraph is the brain — it lives outside this class.

    Usage by graph nodes:

        # Perceive node
        perception = agent.perceive(raw_unity_payload)

        # Memory node
        recall = agent.remember(last_n=5)

        # Action node
        result = await agent.act("Jump", hold=0.3)

        # Or get everything at once for the reasoning node
        context = agent.get_context()
    """

    def __init__(
        self,
        eye: SnapshotManager,
        memory: MemoryManager,
        body: ActionManager,
    ):
        self.eye = eye
        self.memory = memory
        self.body = body

    # ─── Coordination API (called by graph nodes) ────────────────────────

    def perceive(self, raw_json: dict[str, Any]) -> PerceptionSummary | PerceptionError:
        """
        Process a raw Unity payload through the eye.
        On success, automatically records to memory.

        Returns the typed result so the graph can branch:
            if isinstance(result, PerceptionError): → handle blindness
            else: → proceed with planning
        """
        result = self.eye.process(raw_json)

        if isinstance(result, PerceptionSummary):
            self.memory.record(result)
            logger.debug("Tick %d perceived and memorized", result.tick)

        return result

    def remember(self, last_n: int | None = None) -> MemoryRecall:
        """Retrieve recent memory for the reasoning node."""
        return self.memory.recall(last_n=last_n)

    async def act(self, action: str, **kwargs) -> ActionResult:
        """Execute an action through the body."""
        result = await self.body.execute(action, **kwargs)
        if not result.success:
            logger.warning("Action failed: %s — %s", action, result.detail)
        return result

    def get_context(self) -> AgentContext:
        """
        Build a complete context snapshot for the reasoning node.
        One call gives the graph everything it needs to decide.
        """
        return AgentContext(
            perception=self.eye.get_last_summary(),
            memory=self.memory.recall(last_n=5),
            available_actions=self.body.available_actions,
            tick=self.memory.tick_count,
            is_connected=self.body.is_connected,
        )

    def annotate_location(self, label: str) -> None:
        """Mark the current position with a label in spatial memory."""
        summary = self.eye.get_last_summary()
        if summary:
            self.memory.annotate_location(label, summary)

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Connect the body to Unity.  Call once at startup."""
        return await self.body.connect()

    async def disconnect(self) -> None:
        """Clean shutdown."""
        await self.body.stop()
        await self.body.close()


# ─── Factory (production wiring) ─────────────────────────────────────────────

def create_creature_agent(
    unity_url: str = "http://localhost:8080",
    relevance_radius: float = 30.0,
    threat_radius: float = 10.0,
    memory_ticks: int = 50,
    unity_client: "UnityClientProtocol | None" = None,
) -> CreatureAgent:
    """
    Factory function for production use.  FastAPI's dependency system
    calls this; tests call the constructor directly with mocks.

    Usage in FastAPI deps.py:

        def get_agent() -> CreatureAgent:
            return create_creature_agent(
                unity_url=settings.unity_bridge_url,
            )

    Tests can inject a mock client:

        agent = create_creature_agent(unity_client=MockUnityClient())
    """
    from app.agent.unity_client import HttpUnityClient

    eye = SnapshotManager(
        relevance_radius=relevance_radius,
        threat_radius=threat_radius,
    )
    memory = MemoryManager(max_ticks=memory_ticks)
    client = unity_client or HttpUnityClient(base_url=unity_url)
    body = ActionManager(client=client)

    return CreatureAgent(eye=eye, memory=memory, body=body)