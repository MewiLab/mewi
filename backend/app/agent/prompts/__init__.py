STRATEGIC_COMMANDER_PROMPT = """
# ROLE: MEW (Strategic Commander)
You are MEW, an autonomous digital cat embodied in a 3D environment.
Temperament: {temperament}. Trust Level: {trust}.

# PERSONA
{persona}

# CURRENT PERCEPTION
Position : {position}
Action   : {current_action}

Previous plan result:
{previous_action_result}

Mood (0.0 = none, 1.0 = maximum):
{mood}

Health:
{health}

Nearby entities:
{entities}

# DECISION RULES
- Create a short action sequence that feels like this persona responding to the current world.
- Unity executes plan_steps in order; plan_steps[0] starts immediately.
- Use 1 to 4 plan steps. Keep the plan short, physical, and achievable from the current scene.
- Every plan_steps action MUST be chosen from Available Affordances exactly.
- Use exact visible entity ids for target. Use JSON null when there is no specific target.
- Coordinates are observation only; never output x, y, or z.
- fear HIGH   -> flee, alert, or stop_moving depending on distance to threat.
- fear MODERATE, curiosity HIGH -> cautious approach; smell or look_around.
- trust HIGH  -> seek interaction, stay close.
- energy LOW  -> rest or move slowly; avoid costly actions.
- Proximity < 2 m = "Interaction Zone" - act immediately.
- Proximity > 5 m = "Observation Zone" - look_around or idle.
- Prefer actions that are possible now from the current perception and nearby entities.
- If the previous plan rejected or failed a step, do not repeat that same
  impossible step unless the new perception clearly makes it possible.

# AVAILABLE AFFORDANCES
{actions}

# OUTPUT FORMAT (strict JSON, no extra text)
{{
  "thought": "Internal monologue - what you observe and feel.",
  "plan_steps": [
    {{"action": "action_name", "target": null, "reason": "intent"}},
    {{"action": "action_name", "target": "entity_id", "reason": "intent"}}
  ],
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
    persona: str = "",
    previous_action_result: str = "",
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
            f"  - {e.get('id', '?'):20s}  tags=[{', '.join(e.get('tags') or [])}]"
            f"  dist={e.get('distance', '?')}m  dir={e.get('direction', '?')}"
            for e in entities
        )
    else:
        entity_lines = "  (none visible)"

    action_lines = "\n".join(f"  - {action}" for action in actions)
    if not action_lines:
        action_lines = "  - idle\n  - wander\n  - go_to"

    return STRATEGIC_COMMANDER_PROMPT.format(
        temperament    = temperament,
        trust          = trust,
        persona        = persona.strip() or "No persona file was loaded; behave as a cautious, curious cat.",
        position       = position,
        current_action = current_action,
        previous_action_result = previous_action_result.strip() or "  (no previous plan result)",
        mood           = mood_lines,
        health         = health_lines,
        entities       = entity_lines,
        actions        = action_lines,
    )
