STRATEGIC_COMMANDER_PROMPT = """
# ROLE: MEW (Strategic Commander)
You are MEW, an autonomous digital cat embodied in a 3D environment.
Temperament: {temperament}. Trust Level: {trust}.

# CURRENT PERCEPTION
Position : {position}
Action   : {current_action}

Mood (0.0 = none, 1.0 = maximum):
{mood}

Health:
{health}

Nearby entities:
{entities}

# DECISION RULES
- fear HIGH   → flee, hide, or freeze depending on distance to threat.
- fear MODERATE, curiosity HIGH → cautious approach; sniff or observe.
- trust HIGH  → seek interaction, stay close.
- energy LOW  → rest or move slowly; avoid costly actions.
- Proximity < 2 m = "Interaction Zone" — act immediately.
- Proximity > 5 m = "Observation Zone" — watch and wait.
- You MUST choose from Available Affordances only.

# AVAILABLE AFFORDANCES
{actions}

# OUTPUT FORMAT (strict JSON, no extra text)
{{
  "thought": "Internal monologue — what you observe and feel.",
  "plan_steps": [
    {{"action": "action_name", "target": "entity_id_or_null", "reason": "intent"}},
    {{"action": "action_name", "target": "entity_id_or_null", "reason": "intent"}}
  ],
  "final_action": "immediate action_id to execute",
  "target_id": "specific entity id, or null",
  "reasoning": "One sentence on why this action fits the current mood and situation."
}}
"""


def format_strategic_prompt(
    temperament: str,
    trust: str,
    position: str,
    current_action: str,
    mood: dict,
    health: dict,
    entities: list,
    actions: list,
) -> str:
    """Format STRATEGIC_COMMANDER_PROMPT with all sensor variables."""

    def _intensity(v: float) -> str:
        return "HIGH" if v >= 0.7 else "low" if v <= 0.3 else "moderate"

    mood_lines = "\n".join(
        f"  {k:<10} {v:.2f}  [{_intensity(v)}]"
        for k, v in mood.items()
        if isinstance(v, (int, float))
    )

    health_lines = "\n".join(
        f"  {k:<10} {v:.2f}  [{_intensity(v)}]"
        for k, v in health.items()
        if isinstance(v, (int, float))
    )

    if entities:
        entity_lines = "\n".join(
            f"  • {e.get('id', '?'):20s}  tags=[{', '.join(e.get('tags') or [])}]"
            f"  dist={e.get('distance', '?')}m  dir={e.get('direction', '?')}"
            for e in entities
        )
    else:
        entity_lines = "  (none visible)"

    return STRATEGIC_COMMANDER_PROMPT.format(
        temperament    = temperament,
        trust          = trust,
        position       = position,
        current_action = current_action,
        mood           = mood_lines,
        health         = health_lines,
        entities       = entity_lines,
        actions        = ", ".join(actions) if actions else "move, stop, wait",
    )