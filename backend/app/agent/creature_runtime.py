import operator
from typing import Annotated, Any, TypedDict

from app.agent.action_registry import ActionRegistry, ActionResult
from app.agent.memory import MemoryManager, MemoryRecall
from app.agent.perception import SnapshotManager
from app.agent.schemas.perception_schema import PerceptionError, PerceptionSummary


class CreatureRuntime:
    """Per-cat runtime state: perception, memory, and available actions."""

    def __init__(
        self,
        eye: SnapshotManager | None = None,
        memory: MemoryManager | None = None,
        actions: ActionRegistry | None = None,
        persona: str = "",
    ):
        self.eye = eye or SnapshotManager()
        self.memory = memory or MemoryManager()
        self.actions = actions or ActionRegistry()
        self.persona = persona

    def perceive(self, raw_json: dict[str, Any]) -> PerceptionSummary | PerceptionError:
        result = self.eye.process(raw_json)
        if isinstance(result, PerceptionSummary):
            self.memory.record(result)
        return result

    def remember(self, last_n: int | None = None) -> MemoryRecall:
        return self.memory.recall(last_n=last_n)

    def action_result(
        self,
        action: str | None,
        kwargs: dict[str, Any] | None = None,
    ) -> ActionResult:
        return self.actions.result_for(action, kwargs)

    @property
    def available_actions(self) -> list[str]:
        return self.actions.available_actions

    @property
    def action_prompt_descriptions(self) -> list[str]:
        return self.actions.prompt_descriptions

    def state_for_tick(
        self,
        creature_id: str,
        payload: dict[str, Any],
    ) -> "CreatureRuntimeState":
        return {
            "raw_payload": payload,
            "perception": None,
            "perception_error": None,
            "memory_context": None,
            "chosen_action": None,
            "plan_steps": [],
            "reasoning": None,
            "action_result": None,
            "messages": [],
            "runtime": self,
            "persona": self.persona,
            "tick": int(payload.get("tick", 0) or 0),
            "actions_for_prompt": self.action_prompt_descriptions,
            "creature_id": creature_id,
        }


class CreatureRuntimeState(TypedDict):
    """Per-run state passed through the shared behavior graph."""
    creature_id: str
    raw_payload: dict[str, Any]
    perception: dict[str, Any] | None
    perception_error: str | None
    memory_context: dict[str, Any] | None
    chosen_action: dict[str, Any] | None
    plan_steps: list[dict[str, Any]]
    reasoning: str | None
    action_result: dict[str, Any] | None
    messages: Annotated[list, operator.add]
    runtime: CreatureRuntime
    persona: str
    tick: int
    actions_for_prompt: list[str]
