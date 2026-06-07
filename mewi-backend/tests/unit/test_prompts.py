from app.agent.mind.context import format_previous_action_result
from app.agent.mind.experience import TECHNICAL_PROMPT_TOKENS
from app.agent.prompts import format_intent_selection_prompt, format_strategic_prompt


def _assert_no_technical_leak(text: str) -> None:
    for token in TECHNICAL_PROMPT_TOKENS:
        assert token not in text


def test_strategic_prompt_includes_feeling_cues():
    prompt = format_strategic_prompt(
        temperament="curious",
        trust="unknown",
        position="dock",
        current_action="idle",
        mood={"curiosity": 0.8},
        health={"fullness": 0.6},
        entities=[],
        actions=["look_around", "idle"],
        feelings={
            "summary": "smell: old fish from crate",
            "smells": ["strong front near: fresh fish oil; edible"],
            "sounds": ["soft right near: rope creak"],
            "signals": ["cool below contact: damp wood"],
        },
    )

    assert "SENSORY CUES" in prompt
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

    assert "SENSORY CUES" in prompt
    assert "No distinct smell" in prompt


def test_strategic_prompt_uses_semantic_context_without_raw_sections():
    prompt = format_strategic_prompt(
        temperament="curious",
        trust="unknown",
        position="x=0.00, y=0.00, z=0.00",
        current_action="idle",
        mood={"fear": 0.2, "energy": 0.54},
        health={"fullness": 0.0},
        entities=[{"id": "SM_Boat_1_01", "tags": ["prop.boat"], "distance": 3.882}],
        actions=["smell: Investigate by smelling."],
        semantic_context={
            "situation": "The cat is idle on Bamboo Boardwalk, a partly sheltered wooden path within Harbor.",
            "body_state": "Fullness is low — food is urgent, there is no strong fear signal, and energy supports light movement.",
            "sensory_world": ["No distinct smell, sound, or body-contact cue is reported right now."],
            "relevant_targets": ["2 boats nearby ahead-left; targets: SM_Boat_1_3 and SM_Boat_1_01."],
            "decision_focus": ["Fullness is low, but no definite food cue is visible; use smell before eating."],
        },
    )

    assert "Bamboo Boardwalk" in prompt
    assert "food is urgent" in prompt
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

    assert "Bamboo Boardwalk feels overvisited" in prompt
    assert "target id: East_Roof" in prompt


def test_intent_selection_prompt_outputs_directive_not_action_sequence():
    prompt = format_intent_selection_prompt(
        temperament="curious",
        trust="unknown",
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
        intent_affordances={
            "available_intents": ["EXPLORE", "INVESTIGATE", "SEEK_FOOD", "SOCIALIZE", "REST", "SAFETY"],
            "targets": [{"id": "East_Roof", "supports": ["EXPLORE"]}],
        },
    )

    assert "ARBITRATION RULES" in prompt
    assert "Choose one high-level intent" in prompt
    assert "# AVAILABLE INTENT AFFORDANCES" in prompt
    assert "# WHERE SHE IS" in prompt
    assert "# BODY" in prompt
    assert "# EXPLORE FRONTIERS" in prompt
    assert "# SHORT TERM MEMORY" in prompt
    assert '"intent": "<EXPLORE | SEEK_FOOD' in prompt
    assert '"style": "short ActionFSM style hint' in prompt
    assert '"plan_steps"' not in prompt
    assert "East_Roof: supports EXPLORE" in prompt
    assert "target id: East_Roof" in prompt
    assert "Bamboo Boardwalk feels overvisited" in prompt
    # Empty blocks are omitted entirely — fewer tokens, clearer signal.
    assert "# FOOD NEARBY" not in prompt
    assert "# SOCIAL OPTIONS" not in prompt
    assert "# OBJECTS NEARBY" not in prompt
    assert "# WHAT CHANGED" not in prompt


def test_intent_selection_prompt_includes_backend_social_context():
    prompt = format_intent_selection_prompt(
        temperament="curious",
        trust="unknown",
        semantic_context={
            "situation": "The cat is idle on the dock.",
            "body_lines": ["fullness: fullness is high"],
        },
        world_view={
            "peers_in_zone": [
                {
                    "creature_id": "cat_milo",
                    "last_action": "sit",
                    "mood": {"social": 0.7},
                },
            ],
        },
        social_context={
            "delivered_inbox": [
                {
                    "from": "cat_milo",
                    "text": "Milo chirps from the crate.",
                    "tone": "friendly",
                    "target": "cat_mewi",
                },
            ],
            "decision": {
                "spoke": True,
                "utterance": {
                    "from": "cat_mewi",
                    "text": "Mewi sniffs back softly.",
                    "tone": "friendly",
                    "target": "cat_milo",
                },
            },
            "relationships": [
                {
                    "pair": ["cat_mewi", "cat_milo"],
                    "trust": 0.71,
                    "affinity": 0.3,
                    "encounters": 3,
                }
            ],
        },
    )

    assert "# OTHER CATS HERE" in prompt
    assert "cat_milo is here" in prompt
    assert "# SOCIAL EXCHANGE" in prompt
    assert "Heard cat_milo: Milo chirps from the crate." in prompt
    assert "You expressed: Mewi sniffs back softly." in prompt
    assert "trust is strong" in prompt
    assert "affinity is warm" in prompt
    assert "+0.71" not in prompt
    assert "trust 0.71" not in prompt


def test_intent_selection_prompt_renders_related_longterm_memory():
    prompt = format_intent_selection_prompt(
        temperament="curious",
        trust="0.82",
        semantic_context={
            "situation": "The cat is idle on the dock.",
            "body_lines": ["fullness: fullness is high"],
        },
        memory_context={
            "short_term_lines": ["action: Last plan worked."],
            "longterm": [
                {
                    "aspect": "social",
                    "text": "The player has been gentle in recent meetings.",
                }
            ],
        },
    )

    assert "Trust cue: comfortable." in prompt
    assert "# RELATED MEMORY" in prompt
    assert "social: The player has been gentle in recent meetings." in prompt
    assert "Trust Level" not in prompt
    assert "0.82" not in prompt


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
    assert "recovered" not in feedback
    _assert_no_technical_leak(feedback)
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
    assert "failed" not in feedback
    _assert_no_technical_leak(feedback)


def test_previous_action_result_hides_adapter_only_rejection():
    feedback = format_previous_action_result({
        "status": "rejected",
        "steps": [
            {
                "action": "sleep",
                "status": "rejected",
                "reason": "adapter_refused",
            }
        ],
    })

    assert feedback == ""
    _assert_no_technical_leak(feedback)


def test_previous_action_result_ignores_adapter_rejection_inside_working_plan():
    feedback = format_previous_action_result({
        "status": "completed_with_rejections",
        "steps": [
            {
                "action": "vocalize",
                "target": "miso_cat",
                "status": "completed",
                "reason": "Completed",
            },
            {
                "action": "look_at",
                "target": "mewi_cat",
                "status": "completed",
                "reason": "FaceTargetAligned",
            },
            {
                "action": "vocalize",
                "target": "mewi_cat",
                "status": "rejected",
                "reason": "adapter_refused",
            },
        ],
    })

    assert "Your last small plan worked." in feedback
    assert "You made a small sound toward miso_cat." in feedback
    assert "You looked toward mewi_cat." in feedback
    assert "mewi_cat)=rejected" not in feedback
    _assert_no_technical_leak(feedback)


def test_intent_prompt_sanitizes_old_technical_short_term_memory():
    prompt = format_intent_selection_prompt(
        temperament="curious",
        trust="unknown",
        semantic_context={
            "situation": "The cat is idle on the dock.",
            "body_lines": ["energy: energy is low, so rest or stillness fits"],
            "social_cues": [
                "a miso cat; target: miso_cat.",
                "a miso cat; target: miso_cat.",
            ],
            "objects_nearby": [
                "a miso cat; target: miso_cat.",
                "a rope coil; target: rope_1.",
            ],
        },
        memory_context={
            "short_term_lines": [
                "action: Unity reported previous execution status completed_with_rejections. Executed steps: vocalize(miso_cat)=completed because Completed; vocalize(mewi_cat)=rejected because adapter_refused. Selected next intent SOCIALIZE toward miso_cat; Unity will execute the directive after this tick.",
                'social: You said "mrrp?"',
                'social: You said "mrrp?"',
            ],
        },
    )

    _assert_no_technical_leak(prompt)
    assert "# SOCIAL OPTIONS" in prompt
    assert "Current intention: SOCIALIZE near miso_cat." in prompt
    assert prompt.count('social: You said "mrrp?"') == 1
    assert prompt.count("a miso cat; target: miso_cat.") == 1
    assert "a rope coil; target: rope_1." in prompt
