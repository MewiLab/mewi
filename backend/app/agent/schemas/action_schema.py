from dataclasses import dataclass, field


@dataclass
class ActionResult:
    """Typed outcome of an action execution."""
    success: bool
    action: str
    detail: str = ""
    raw_response: dict | None = None

@dataclass
class ActionSchema:
    """Description of one available action from Unity."""
    name: str
    action_type: str = "button"
    description: str = ""
    parameters: dict[str, str] = field(default_factory=dict)