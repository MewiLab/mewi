import operator
from typing import Annotated, Any, TypedDict

from app.agent.action_registry import ActionRegistry, ActionResult
from app.agent.memory import MemoryManager, MemoryRecall
from app.agent.perception import SnapshotManager
from app.agent.prompt_loader import PersonaManager
from app.agent.schemas.perception_schema import PerceptionError, PerceptionSummary
from app.agent.schemas.place_memory_schema import PlaceMemoryContextDict


class CreatureRuntime:
    """Per-cat runtime state: perception, memory, and available actions."""

    def __init__(
        self,
        eye: SnapshotManager | None = None,
        memory: MemoryManager | None = None,
        actions: ActionRegistry | None = None,
        persona: str = "",
        persona_manager: PersonaManager | None = None,
        creature_id: str = "",
    ):
        self.eye = eye or SnapshotManager()
        self.memory = memory or MemoryManager()
        self.actions = actions or ActionRegistry()
        self.creature_id = creature_id
        if persona_manager is not None:
            self.persona = persona_manager.for_creature(creature_id)
        else:
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
            "structured_context": None,
            "memory_context": None,
            "memory_state": None,
            "place_memory_context": None,
            "world_view": None,
            "social_context": None,
            "dialogue": [],
            "intent_decision": None,
            "intent_affordances": None,
            "domain_intents": [],
            "intent_proposals": [],
            "chosen_action": None,
            "plan_steps": [],
            "tool_results": [],
            "social_effects": [],
            "wake_targets": [],
            "reasoning": None,
            "action_result": None,
            "memory_write": None,
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
    structured_context: dict[str, Any] | None
    memory_context: dict[str, Any] | None
    memory_state: dict[str, Any] | None
    place_memory_context: PlaceMemoryContextDict | None
    world_view: dict[str, Any] | None
    social_context: dict[str, Any] | None
    dialogue: list[dict[str, Any]]
    intent_decision: dict[str, Any] | None
    intent_affordances: dict[str, Any] | None
    domain_intents: list[dict[str, Any]]
    intent_proposals: list[dict[str, Any]]
    chosen_action: dict[str, Any] | None
    plan_steps: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    social_effects: list[dict[str, Any]]
    wake_targets: list[str]
    reasoning: str | None
    action_result: dict[str, Any] | None
    memory_write: dict[str, Any] | None
    messages: Annotated[list, operator.add]
    runtime: CreatureRuntime
    persona: str
    tick: int
    actions_for_prompt: list[str]
