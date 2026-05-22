from app.agent.mind.context import format_previous_action_result
from app.agent.prompts import format_slow_mind_prompt, format_strategic_prompt


def test_strategic_prompt_includes_feeling_cues():
    prompt = format_strategic_prompt(
        temperament="curious",
        trust="unknown",
        position="dock",
        current_action="idle",
        mood={"curiosity": 0.8},
        health={"hunger": 0.4},
        entities=[],
        actions=["look_around", "idle"],
        feelings={
            "summary": "smell: old fish from crate",
            "smells": ["strong front near: fresh fish oil; edible"],
            "sounds": ["soft right near: rope creak"],
            "signals": ["cool below contact: damp wood"],
        },
    )

    assert "SENSORY MEANING" in prompt
    assert "old fish" in prompt
    assert "fresh fish oil" in prompt
    assert "rope creak" in prompt
    assert "damp wood" in prompt
    assert "0.8" not in prompt
    assert "Mood (0.0" not in prompt
    assert "dist=" not in prompt


def test_strategic_prompt_handles_missing_feelings():
    prompt = format_strategic_prompt(
        temperament="curious",
        trust="unknown",
        position="dock",
        current_action="idle",
        mood={},
        health={},
        entities=[],
        actions=["idle"],
    )

    assert "SENSORY MEANING" in prompt
    assert "No distinct smell" in prompt


def test_strategic_prompt_uses_semantic_context_without_raw_sections():
    prompt = format_strategic_prompt(
        temperament="curious",
        trust="unknown",
        position="x=0.00, y=0.00, z=0.00",
        current_action="idle",
        mood={"fear": 0.2, "energy": 0.54},
        health={"hunger": 1.0},
        entities=[{"id": "SM_Boat_1_01", "tags": ["prop.boat"], "distance": 3.882}],
        actions=["smell: Investigate by smelling."],
        semantic_context={
            "situation": "The cat is idle on Bamboo Boardwalk, a partly sheltered wooden path within Harbor.",
            "body_state": "Food is urgent, there is no strong fear signal, and energy supports light movement.",
            "sensory_world": ["No distinct smell, sound, or body-contact cue is reported right now."],
            "relevant_targets": ["2 boats nearby ahead-left; targets: SM_Boat_1_3 and SM_Boat_1_01."],
            "decision_focus": ["Hunger is urgent, but no definite food cue is visible; use smell before eating."],
        },
    )

    assert "Bamboo Boardwalk" in prompt
    assert "Food is urgent" in prompt
    assert "SM_Boat_1_01" in prompt
    assert "3.882" not in prompt
    assert "x=0.00" not in prompt


def test_strategic_prompt_includes_place_memory_context():
    prompt = format_strategic_prompt(
        temperament="curious",
        trust="unknown",
        position="dock",
        current_action="idle",
        mood={},
        health={},
        entities=[],
        actions=["go_to", "idle"],
        place_memory_context={
            "lines": [
                "Current place: Bamboo Boardwalk feels overvisited.",
                "Best exploration target: East Roof; target id: East_Roof.",
            ],
        },
    )

    assert "PLACE MEMORY" in prompt
    assert "Bamboo Boardwalk feels overvisited" in prompt
    assert "target id: East_Roof" in prompt


def test_slow_mind_prompt_outputs_intent_not_action_sequence():
    prompt = format_slow_mind_prompt(
        temperament="curious",
        trust="unknown",
        actions=["go_to: Move toward a place.", "idle: Wait."],
        semantic_context={
            "situation": "The cat is idle on Bamboo Boardwalk.",
            "body_state": "Curiosity is available and energy supports movement.",
            "body_lines": [
                "food: food is not pressing",
                "fear: there is no strong fear signal",
                "curiosity: curiosity is available for a small inspection",
                "social: social contact is not the main draw",
                "energy: energy supports light movement",
            ],
            "sensory_world": ["No danger is present."],
            "food_nearby": [],
            "social_cues": [],
            "objects_nearby": [],
            "whats_changed": [],
            "relevant_targets": ["No meaningful nearby target is currently visible."],
            "decision_focus": ["Choose a durable intent."],
        },
        place_memory_context={
            "lines": [
                "Current place: Bamboo Boardwalk feels overvisited.",
                "Best exploration target: East Roof; target id: East_Roof.",
            ],
        },
        memory_context={"short_term_lines": ["action: Last plan worked."]},
    )

    assert "SLOW MIND RULES" in prompt
    assert "Choose one durable intent" in prompt
    assert "# ONE-SHOT EXAMPLE" in prompt
    assert "# WHERE SHE IS" in prompt
    assert "# BODY" in prompt
    assert "# EXPLORE FRONTIERS" in prompt
    assert "# SHORT TERM MEMORY" in prompt
    assert "# LAST TICK" in prompt
    assert '"intent": "<EXPLORE | SEEK_FOOD' in prompt
    assert '"style": "short physical style hint' in prompt
    assert "AVAILABLE AFFORDANCES" not in prompt
    assert '"plan_steps"' not in prompt
    assert "target id: East_Roof" in prompt
    assert "Bamboo Boardwalk feels overvisited" in prompt
    # Empty blocks are omitted entirely — fewer tokens, clearer signal.
    assert "# FOOD NEARBY" not in prompt
    assert "# SOCIAL CUES" not in prompt
    assert "# OBJECTS NEARBY" not in prompt
    assert "# WHAT CHANGED" not in prompt


def test_previous_action_result_uses_semantic_step_recap():
    # Unity currently guarantees go_to ends up at the target (recovery teleport
    # fallback). The LLM-visible recap must therefore treat "recovered" the
    # same as "completed" — internal status differentiation is preserved in
    # code but invisible in the prompt.
    feedback = format_previous_action_result({
        "status": "completed_with_recoveries",
        "steps": [
            {
                "action": "go_to",
                "target": "SM_Fish_1",
                "status": "recovered",
                "reason": "recovered_via_teleport:WarpedToNavMesh",
            },
            {
                "action": "eat",
                "target": "SM_Fish_1",
                "status": "completed",
                "reason": "consumed_bite",
            },
        ],
    })

    # Phenomenological preamble — recoveries roll into the regular success line.
    assert "Your last small plan worked." in feedback
    # Recovered go_to reads identically to a natural arrival.
    assert "You walked to SM_Fish_1." in feedback
    # Eat success reads as a bite, not a function status.
    assert "You took a bite from SM_Fish_1" in feedback
    # The recovery detail is not surfaced to the LLM.
    assert "not by walking" not in feedback
    assert "had to be forced" not in feedback
    # No raw function-status leakage.
    assert "go_to on" not in feedback


def test_previous_action_result_marks_eat_failure_semantically():
    feedback = format_previous_action_result({
        "status": "completed_with_failures",
        "steps": [
            {
                "action": "go_to",
                "target": "SM_Fish_1",
                "status": "completed",
                "reason": "Arrived",
            },
            {
                "action": "eat",
                "target": "SM_Fish_1",
                "status": "failed",
                "reason": "not_confirmed_by_world",
            },
        ],
    })

    assert "Your last plan partly worked." in feedback
    assert "You walked to SM_Fish_1." in feedback
    assert "couldn't reach it" in feedback
