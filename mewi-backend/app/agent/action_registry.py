from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    description: str


@dataclass(frozen=True)
class ActionResult:
    status: str
    action: str
    target: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "target": self.target,
        }


ACTION_DEFINITIONS = (
    ActionDefinition("idle", "Do nothing for this tick."),
    ActionDefinition("wander", "Move around casually without a fixed target."),
    ActionDefinition("go_to", "Move toward a place or point of interest."),
    ActionDefinition("follow", "Stay near and move with a target."),
    ActionDefinition("stop_moving", "Stop current movement."),
    ActionDefinition("eat", "Eat available food."),
    ActionDefinition("drink", "Drink available water."),
    ActionDefinition("sit", "Sit down."),
    ActionDefinition("lie", "Lie down."),
    ActionDefinition("sleep", "Sleep or rest deeply."),
    ActionDefinition("groom", "Clean self."),
    ActionDefinition("smell", "Investigate by smelling."),
    ActionDefinition("alert", "Become attentive to possible danger or interest."),
    ActionDefinition("vocalize", "Make a sound."),
    ActionDefinition("scratch", "Scratch a nearby surface or self."),
    ActionDefinition("look_around", "Scan the surroundings."),
    ActionDefinition("nod_head", "Make a small head gesture."),
    ActionDefinition("flee", "Move away from danger."),
)


class ActionRegistry:
    def __init__(self, actions: tuple[ActionDefinition, ...] = ACTION_DEFINITIONS):
        self._actions = actions
        self._by_name = {action.name: action for action in actions}

    @property
    def available_actions(self) -> list[str]:
        return [action.name for action in self._actions]

    @property
    def prompt_descriptions(self) -> list[str]:
        return [
            f"{action.name}: {action.description}"
            for action in self._actions
        ]

    def result_for(
        self,
        action: str | None,
        kwargs: dict[str, Any] | None = None,
    ) -> ActionResult:
        action = action or "idle"
        if action not in self._by_name:
            action = "idle"
        kwargs = kwargs or {}
        return ActionResult(
            status="done",
            action=action,
            target=str(kwargs.get("target") or ""),
        )
