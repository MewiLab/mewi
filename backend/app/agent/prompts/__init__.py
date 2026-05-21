STRATEGIC_COMMANDER_PROMPT = """
# ROLE: MEW (Strategic Commander)
You are MEW, an autonomous digital cat embodied in a 3D environment.
Temperament: {temperament}. Trust Level: {trust}.

# PERSONA
{persona}

# CURRENT PERCEPTION
{situation}

# BODY AND MOTIVATION
{body_state}

# SENSORY MEANING
{sensory_world}

# RELEVANT TARGETS
{relevant_targets}

# RECENT PLAN FEEDBACK
{previous_action_result}

# DECISION RULES
- Create a short action sequence that feels like this persona responding to the current world.
- Unity executes plan_steps in order; plan_steps[0] starts immediately.
- Use 1 to 4 plan steps. Keep the plan short, physical, and achievable from the current scene.
- Every plan_steps action MUST be chosen from Available Affordances exactly.
- Use exact target ids from Relevant Targets when acting on a visible object.
- Use JSON null when there is no specific target.
- Do not invent coordinates, distances, hidden objects, or raw sensor values.
- Treat the semantic context as already interpreted; reason from meaning, not numbers.
- If recent feedback says an action was rejected or unmapped, avoid that action for now.
- Prefer the smallest physical action that advances the current motivation.

# DECISION FOCUS
{decision_focus}

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
    feelings: dict | None = None,
    semantic_context: dict | None = None,
    persona: str = "",
    previous_action_result: str = "",
) -> str:
    """Format STRATEGIC_COMMANDER_PROMPT with all sensor variables."""
    context = semantic_context or _legacy_semantic_context(
        position=position,
        current_action=current_action,
        mood=mood,
        health=health,
        entities=entities,
        feelings=feelings,
    )

    action_lines = "\n".join(f"  - {action}" for action in actions)
    if not action_lines:
        action_lines = "  - idle\n  - wander\n  - go_to"

    return STRATEGIC_COMMANDER_PROMPT.format(
        temperament    = temperament,
        trust          = trust,
        persona        = persona.strip() or "No persona file was loaded; behave as a cautious, curious cat.",
        situation      = _section_text(context.get("situation")),
        body_state     = _section_text(context.get("body_state")),
        sensory_world  = _bullet_lines(context.get("sensory_world")),
        relevant_targets = _bullet_lines(context.get("relevant_targets")),
        decision_focus = _bullet_lines(context.get("decision_focus")),
        previous_action_result = previous_action_result.rstrip() or "  - no previous plan result",
        actions        = action_lines,
    )


def _legacy_semantic_context(
    position: str,
    current_action: str,
    mood: dict,
    health: dict,
    entities: list,
    feelings: dict | None,
) -> dict:
    """Fallback for tests and older call sites; still hides raw values."""
    hunger = _number(health.get("hunger") if isinstance(health, dict) else None)
    fear = _number(mood.get("fear") if isinstance(mood, dict) else None)
    energy = _number(mood.get("energy") if isinstance(mood, dict) else None, default=1.0)

    targets = []
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        target_id = str(entity.get("id") or "").strip()
        tags = [str(tag).split(".")[-1].replace("_", " ") for tag in entity.get("tags") or [] if tag]
        label = " and ".join(tags[:2]) or target_id
        if label:
            target = f"{label}"
            if target_id:
                target += f"; target: {target_id}"
            targets.append(target + ".")

    sensory = _format_feeling_meanings(feelings)
    place = _semantic_place_text(position)
    return {
        "situation": f"The cat is {current_action or 'idle'} at {place}.",
        "body_state": _body_sentence(hunger, fear, energy),
        "sensory_world": sensory,
        "relevant_targets": targets or ["No meaningful nearby target is currently visible."],
        "decision_focus": ["Choose a small action that fits the interpreted situation."],
    }


def _semantic_place_text(position: str) -> str:
    text = str(position or "").strip()
    if not text:
        return "an unspecified place"
    if "x=" in text or "y=" in text or "z=" in text:
        return "the current area"
    return text


def _body_sentence(hunger: float, fear: float, energy: float) -> str:
    parts: list[str] = []
    parts.append("food is urgent" if hunger >= 0.7 else "food is not urgent")
    parts.append("safety should come first" if fear >= 0.7 else "there is no strong fear signal")
    parts.append("energy is low" if energy <= 0.3 else "energy supports light movement")
    return ", ".join(parts) + "."


def _format_feeling_meanings(feelings: dict | None) -> list[str]:
    if not isinstance(feelings, dict):
        return ["No distinct smell, sound, or body-contact cue is reported right now."]

    lines: list[str] = []
    summary = str(feelings.get("summary") or "").strip()
    if summary:
        lines.append(summary)

    for key, label in [
        ("smells", "Smell"),
        ("sounds", "Sound"),
        ("signals", "Body signal"),
    ]:
        values = _string_values(feelings.get(key))
        lines.extend(f"{label}: {_meaningful_feeling(value)}." for value in values[:6])

    known = {"summary", "smells", "sounds", "signals"}
    for key, value in feelings.items():
        if key in known:
            continue
        values = _string_values(value)
        label = key.replace("_", " ").title()
        lines.extend(f"{label}: {_meaningful_feeling(item)}." for item in values[:4])

    return lines or ["No distinct smell, sound, or body-contact cue is reported right now."]


def _meaningful_feeling(value: str) -> str:
    text = str(value).strip()
    if ":" in text:
        _prefix, text = text.split(":", 1)
    return text.strip().replace("_", "-").rstrip(".")


def _section_text(value) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "(unknown)"


def _bullet_lines(value) -> str:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
    return "\n".join(f"  - {item}" for item in items) if items else "  - (none)"


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_values(value) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]
