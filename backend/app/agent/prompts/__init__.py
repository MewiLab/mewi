from typing import TYPE_CHECKING

from app.agent.prompts.sections import (
    action_lines as _action_lines,
    build_dynamic_section as _build_dynamic_section,
    bullet_lines as _bullet_lines,
    place_memory_lines as _place_memory_lines,
    section_text as _section_text,
)

if TYPE_CHECKING:
    from app.agent.schemas.place_memory_schema import PlaceMemoryContextDict


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

# PLACE MEMORY
{place_memory}

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
- Use exact target ids from Place Memory only when it explicitly provides a target id.
- Use JSON null when there is no specific target.
- Do not invent coordinates, distances, hidden objects, or raw sensor values.
- Treat the semantic context as already interpreted; reason from meaning, not numbers.
- If recent feedback says an action was rejected or unmapped, avoid that action for now.
- When curiosity and energy are available, and hunger/fear are not urgent, prefer new or stale places over overvisited places.
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

SLOW_MIND_PROMPT_STATIC = """
# ROLE: MEW (Slow Mind)
You are MEW, an autonomous digital cat embodied in a 3D environment.
Temperament: {temperament}. Trust Level: {trust}.

# PERSONA
{persona}

# INTENT CATALOG
- EXPLORE: curiosity should carry the cat toward a new or stale place.
- SEEK_FOOD: hunger and a food cue should guide the cat toward food.
- SEEK_PLAYER: the cat wants to locate or stay near a trusted human.
- SOCIALIZE: the cat wants gentle contact with a nearby trusted being.
- INVESTIGATE: the cat wants to inspect a nearby cue, object, smell, or sound.
- REST: low energy or comfort should guide stillness, sitting, lying, or sleep.
- SAFETY: fear, danger, or failed movement should guide distance or alertness.
- IDLE: nothing strong is pulling the body yet.

# SLOW MIND RULES
- Choose one durable intent, not a concrete action sequence.
- Fast Mind will translate the intent and style into Unity actions.
- Use exact target ids only from Place Memory or Relevant Targets.
- Prefer EXPLORE when curiosity and energy are available and hunger/fear are not urgent.
- Prefer SEEK_FOOD when hunger is urgent and food is visible or scented.
- Prefer REST when energy is low.
- Prefer SAFETY when fear or recent failed/rejected movement matters.
- Express how this cat would physically approach the intent. The style should come from persona, mood, and recent feedback.

# ONE-SHOT EXAMPLE
If the current prompt says hunger is urgent and Relevant Targets contains "fish nearby; target: SM_Fish_1", a good Slow Mind output is:
{{
  "intent": "SEEK_FOOD",
  "target_id": "SM_Fish_1",
  "mood": "hungry but watchful",
  "style": "cautious sniff-first approach",
  "reasoning": "The food cue is strong, but this cat should confirm it with scent before committing."
}}
Use this only as an example of level and shape; use the current prompt's real target ids.

# OUTPUT FORMAT
Return exactly one JSON object, with no markdown and no extra text.
Replace placeholders with real values from the current context; do not return angle brackets.
{{
  "intent": "<EXPLORE | SEEK_FOOD | SEEK_PLAYER | SOCIALIZE | INVESTIGATE | REST | SAFETY | IDLE>",
  "target_id": null,
  "mood": "brief embodied mood",
  "style": "short physical style hint for Fast Mind, e.g. cautious sniff-first, direct hungry approach, gentle social approach",
  "reasoning": "One sentence explaining why this intent fits."
}}
"""


# The dynamic suffix is assembled from typed need-blocks rather than from a
# fixed template, so empty blocks vanish entirely (saves tokens, reduces
# "nothing here" noise). See format_slow_mind_prompt_parts below.
SLOW_MIND_PROMPT_DYNAMIC = ""


# Legacy single-string template kept for tests that still assert on the
# combined output. New code should prefer format_slow_mind_prompt_parts.
SLOW_MIND_PROMPT = SLOW_MIND_PROMPT_STATIC


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
    place_memory_context: "PlaceMemoryContextDict | None" = None,
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

    return STRATEGIC_COMMANDER_PROMPT.format(
        temperament    = temperament,
        trust          = trust,
        persona        = persona.strip() or "No persona file was loaded; behave as a cautious, curious cat.",
        situation      = _section_text(context.get("situation")),
        body_state     = _section_text(context.get("body_state")),
        sensory_world  = _bullet_lines(context.get("sensory_world")),
        place_memory   = _bullet_lines(
            _place_memory_lines(place_memory_context),
            empty="  - no place memory yet",
        ),
        relevant_targets = _bullet_lines(context.get("relevant_targets")),
        decision_focus = _bullet_lines(context.get("decision_focus")),
        previous_action_result = previous_action_result.rstrip() or "  - no previous plan result",
        actions        = _action_lines(actions),
    )


def format_slow_mind_prompt_parts(
    temperament: str,
    trust: str,
    actions: list,
    semantic_context: dict | None = None,
    place_memory_context: "PlaceMemoryContextDict | None" = None,
    memory_context: dict | None = None,
    persona: str = "",
    previous_action_result: str = "",
) -> tuple[str, str]:
    """Return (static_prefix, dynamic_suffix) for prompt caching.

    The static prefix only depends on persona + temperament + trust and is safe
    to cache across ticks for the same creature. The dynamic suffix carries
    per-tick observations.
    """
    context = semantic_context or {}

    static_text = SLOW_MIND_PROMPT_STATIC.format(
        temperament=temperament,
        trust=trust,
        persona=persona.strip() or "No persona file was loaded; behave as a cautious, curious cat.",
    )
    dynamic_text = _build_dynamic_section(
        context=context,
        place_memory_context=place_memory_context,
        memory_context=memory_context,
        previous_action_result=previous_action_result,
    )
    return static_text, dynamic_text




def format_slow_mind_prompt(
    temperament: str,
    trust: str,
    actions: list,
    semantic_context: dict | None = None,
    place_memory_context: "PlaceMemoryContextDict | None" = None,
    memory_context: dict | None = None,
    persona: str = "",
    previous_action_result: str = "",
) -> str:
    static_text, dynamic_text = format_slow_mind_prompt_parts(
        temperament=temperament,
        trust=trust,
        actions=actions,
        semantic_context=semantic_context,
        place_memory_context=place_memory_context,
        memory_context=memory_context,
        persona=persona,
        previous_action_result=previous_action_result,
    )
    return static_text + dynamic_text


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
