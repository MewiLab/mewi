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
    """Describes one action the cat can perform, understood by CreatureMotor in Unity."""
    name: str
    description: str
    parameters: dict[str, str] = field(default_factory=dict)

    def prompt_line(self) -> str:
        if self.parameters:
            params = ", ".join(f"{k}: {v}" for k, v in self.parameters.items())
            return f"  - {self.name}({params}) — {self.description}"
        return f"  - {self.name} — {self.description}"


# ── Mewi action registry ──────────────────────────────────────────────────────
# Single source of truth.  Sync with CreatureMotor.EnterIntent() in Unity
# whenever actions are added or removed.

MEWI_ACTIONS: list[ActionSchema] = [
    # ── Navigation (routed through MAnimalAIControl + NavMesh) ──
    ActionSchema(
        "go_to", "Navigate to a world position OR a named scene object",
        {
            "x":      "float (omit or 0 if using target name)",
            "y":      "float (ground = 0, omit if using target name)",
            "z":      "float (omit or 0 if using target name)",
            "target": "str OPTIONAL — scene object name e.g. 'SM_Boat_1_01_LOD0' (overrides x/y/z)",
        },
    ),
    ActionSchema(
        "follow", "Continuously follow a named scene object",
        {"target": "str  e.g. 'Player' | 'FoodBowl' | 'HomeArea'"},
    ),
    ActionSchema("wander",      "Roam to a random nearby point"),
    ActionSchema("idle",        "Stand still"),
    ActionSchema("flee",        "Sprint away from the nearest threat"),
    ActionSchema("investigate", "Sneak toward the closest player"),
    # ── Expressions (Malbers Action mode, one-shot) ──
    ActionSchema("sit",       "Sit down"),
    ActionSchema("eat",       "Eat from the food bowl"),
    ActionSchema("drink",     "Drink water"),
    ActionSchema("sleep",     "Lie down and sleep"),
    ActionSchema("groom",     "Groom self"),
    ActionSchema("vocalize",  "Meow or make a sound"),
    ActionSchema("alert",     "Alert / threat-display stance"),
    ActionSchema("smell",     "Sniff the ground or an object"),
    # ── Control ──
    ActionSchema("wait",      "Do nothing this tick — skip action entirely"),
]

VALID_ACTION_NAMES: frozenset[str] = frozenset(s.name for s in MEWI_ACTIONS)


def get_prompt_block() -> str:
    """Return the action registry formatted as an LLM system-prompt section."""
    lines = ["Available actions (use ONLY these exact names):"]
    lines += [s.prompt_line() for s in MEWI_ACTIONS]
    lines += [
        "",
        "kwargs rules:",
        "  go_to by name   → {\"target\": \"SM_Boat_1_01_LOD0\"}  (preferred when you know the object name)",
        "  go_to by coords → {\"x\": float, \"y\": 0.0, \"z\": float}  (use when no name is available)",
        "  follow          → {\"target\": \"<name>\"}",
        "  all other actions → {} (no kwargs needed)",
    ]
    return "\n".join(lines)
