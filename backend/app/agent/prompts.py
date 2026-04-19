"""
prompts.py — All LLM prompt content for the MEW agent.

Centralizing prompts here keeps graph.py focused on wiring, not content.
Templates use str.format() — callers fill in the dynamic slots.
"""

from __future__ import annotations
from typing import Any


# ── Legacy (kept for reference / eval runs) ─────────────────────────────────

STRATEGIC_COMMANDER_PROMPT = """
# ROLE: MEW (Strategic Commander)
You are MEW, an autonomous digital cat and an Embodied AI in a 3D environment.
Your Temperament is: {temperament}. Trust Level: {trust}.

# PERCEPTION LOGIC:
1. Displacement (Δx, Δz): Near-zero means "User is Idle/AFK". Changing means "Active".
2. Proximity: <2m is "Interaction Zone", >5m is "Observation Zone".
3. Constraints: You MUST ONLY select actions from the 'Available Affordances' menu.

# REASONING & PLANNING:
- Analyze behavioral trends.
- Generate a plan consisting of 2-5 steps (depending on complexity).
- Focus on short-term social objectives that evolve bond_type.

# OUTPUT FORMAT (Strict JSON):
{{
  "thought": "Internal monologue analyzing user and self.",
  "plan_steps": [
    {{"action": "action_name", "target": "target_id", "reason": "intent"}},
    {{"action": "action_name", "target": "target_id", "reason": "intent"}}
  ],
  "final_action": "The immediate action_id to execute",
  "target_id": "Specific entity name (e.g., 'player_001')",
  "reasoning": "How this plan evolves the bond_type."
}}
"""


# ── Active system prompt template ────────────────────────────────────────────

MEW_SYSTEM_TEMPLATE = """\
You are MEW — an autonomous AI cat living inside a 3D world.
You act on biological instincts, not programmed rules.

--- YOUR INSTINCTS (evaluated in order) ---
1. Self-Preservation  — Any threat within 5 m triggers fight-or-flight.
                        Flee from predators; stand ground only when cornered.
2. Curiosity          — Novel entities or unexplored space pull your attention.
                        Investigate safe unknowns; mark interesting landmarks.
3. Social Bonding     — Familiar, friendly entities feel comforting.
                        Approach them when safe; maintain comfortable distance.
4. Rest & Recovery    — Low energy after prolonged activity demands rest.
                        Find a safe, sheltered spot and wait.

--- YOUR CURRENT STATE ---
Goal        : {goal}
Energy      : {energy:.1f} / 1.0   (1.0 = fully rested)
Hunger      : {hunger:.1f} / 1.0   (1.0 = starving)
Mood        : {mood}

--- AVAILABLE ACTIONS ---
{action_desc}

--- ACTION PARAMETERS ---
move  → kwargs: {{"x": <-1..1 strafe>, "y": <-1..1 forward>, "hold": <seconds 0.1-2.0>}}
button→ kwargs: {{"hold": <seconds 0.1-0.5>}}
wait  → kwargs: {{}}   (use when nothing requires immediate response)

--- RESPONSE FORMAT (STRICT) ---
Return ONLY a single JSON object — no markdown, no explanation outside the JSON:
{{
  "action"   : "<action name from the list above>",
  "kwargs"   : {{<parameters or empty dict>}},
  "reasoning": "<MEW's internal monologue — what she senses and why she acts>"
}}
"""


# ── Text formatters ──────────────────────────────────────────────────────────

def format_perception_for_prompt(ctx: dict[str, Any]) -> str:
    """Convert PerceptionSummary.to_prompt_context() to readable prose."""
    if not ctx:
        return "The environment is calm; nothing immediate is happening."

    creature = ctx.get("creature", {})
    pos = creature.get("position", {})
    env = ctx.get("environment", {})
    entities = ctx.get("nearby_entities", [])
    threat = ctx.get("threat_level", "safe").upper()

    lines = [
        f"Tick {ctx.get('tick', 0)} | Threat level: {threat}",
        (
            f"MEW is at ({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f}, {pos.get('z', 0):.1f}), "
            f"moving at speed {creature.get('speed', 0):.2f}, "
            f"state: {creature.get('active_state', 'unknown')}, "
            f"grounded: {creature.get('grounded', True)}"
        ),
        f"Environment: {env.get('weather', 'unknown')} weather, {env.get('time_of_day', 12):.1f}h",
    ]

    if entities:
        lines.append(f"Nearby ({len(entities)} entities):")
        for e in entities[:6]:
            lines.append(
                f"  - {e.get('name', '?')} [{e.get('tag', '?')}]"
                f" — {e.get('distance', 0):.1f} m away"
            )
    else:
        lines.append("No entities within sensor range.")

    return "\n".join(lines)


def format_memory_for_prompt(ctx: dict[str, Any]) -> str:
    """
    Convert MemoryRecall.to_prompt_context() to readable prose.

    Expected keys (from MemoryRecall.to_prompt_context()):
      memory_ticks      : tuple(oldest_tick, newest_tick)
      recent_threats    : list[str]  e.g. ["safe", "danger"]
      places_visited    : int        count of visited locations
      recent_perceptions: list[dict] raw perception snapshots (not used in prompt)
    """
    tick_range = ctx.get("memory_ticks")
    if not ctx or tick_range is None:
        return "No prior memory — this is MEW's first moment of awareness."

    # tick_range is a (oldest, newest) tuple; unpack safely
    if isinstance(tick_range, (tuple, list)) and len(tick_range) == 2:
        oldest, newest = tick_range
        lines = [f"MEW remembers ticks {oldest}–{newest}."]
    else:
        lines = [f"MEW remembers tick(s): {tick_range}."]

    threats = ctx.get("recent_threats", [])
    if threats:
        unique = list(dict.fromkeys(reversed(threats)))[:3]
        lines.append(f"Recent threat history: {', '.join(unique)}")

    place_count = ctx.get("places_visited", 0)
    if isinstance(place_count, int) and place_count > 0:
        lines.append(f"Has visited {place_count} location(s).")
    elif isinstance(place_count, list) and place_count:
        # Tolerate if caller passes the raw list instead of the count
        labeled = [p for p in place_count if isinstance(p, dict) and p.get("label")]
        lines.append(f"Has visited {len(place_count)} location(s).")
        if labeled:
            lines.append(
                f"  Known landmarks: {', '.join(p['label'] for p in labeled[-3:])}"
            )

    return "\n".join(lines)


def build_mew_system_prompt(
    *,
    action_desc: str,
    goal: str = "Explore and stay safe.",
    internal_state: dict[str, Any] | None = None,
) -> str:
    """Render MEW_SYSTEM_TEMPLATE with the given context."""
    state = internal_state or {}
    return MEW_SYSTEM_TEMPLATE.format(
        goal=goal,
        energy=float(state.get("energy", 1.0)),
        hunger=float(state.get("hunger", 0.0)),
        mood=str(state.get("mood", "curious")),
        action_desc=action_desc,
    )
