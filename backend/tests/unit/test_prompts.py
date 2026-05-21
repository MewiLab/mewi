from app.agent.prompts import format_strategic_prompt


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
