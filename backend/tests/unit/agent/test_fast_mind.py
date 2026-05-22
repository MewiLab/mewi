from app.agent.mind.fast import (
    chosen_action_from_plan,
    fast_mind_reasoning,
    parse_fast_mind_response,
)
from app.agent.prompts.fast_mind import format_fast_mind_prompt


AVAILABLE = [
    "idle",
    "wander",
    "go_to",
    "follow",
    "eat",
    "sit",
    "lie",
    "sleep",
    "smell",
    "alert",
    "look_around",
    "flee",
]


def test_fast_mind_prompt_receives_intent_style_and_affordances() -> None:
    prompt = format_fast_mind_prompt(
        intent_decision={
            "intent": "SEEK_FOOD",
            "target_id": "SM_Fish_1",
            "mood": "hungry but careful",
            "style": "cautious sniff-first",
            "reasoning": "Food is urgent and a fish cue is nearby.",
        },
        actions=["go_to: Move toward a place.", "eat: Eat available food."],
        semantic_context={
            "situation": "The cat is idle on the dock.",
            "body_state": "Food is urgent.",
            "sensory_world": ["Fish scent is nearby."],
            "relevant_targets": ["fish nearby; target: SM_Fish_1."],
        },
        place_memory_context={"lines": ["Current place: Dock feels familiar."]},
        previous_action_result="  - no previous plan result",
        max_plan_steps=8,
    )

    assert "# ROLE: MEW (Fast Mind)" in prompt
    assert "intent: SEEK_FOOD" in prompt
    assert "style: cautious sniff-first" in prompt
    assert "target_id: SM_Fish_1" in prompt
    assert "go_to: Move toward a place." in prompt
    assert "eat: Eat available food." in prompt
    assert "Prefer 5 to 8 steps" in prompt
    assert "# ONE-SHOT EXAMPLE" in prompt
    assert "SHORT TERM MEMORY" in prompt
    assert '"groom"' in prompt
    assert "INTENT CATALOG" not in prompt


def test_parse_fast_mind_response_filters_unknown_actions_and_caps_steps() -> None:
    parsed = parse_fast_mind_response(
        """
        ```json
        {
          "plan_steps": [
            {"action": "smell", "target": null, "reason": "sample scent"},
            {"action": "invent_magic", "target": null, "reason": "bad"},
            {"action": "go_to", "target": "SM_Fish_1", "reason": "approach"},
            {"action": "smell", "target": "SM_Fish_1", "reason": "confirm"},
            {"action": "eat", "target": "SM_Fish_1", "reason": "bite"},
            {"action": "sit", "target": null, "reason": "settle"},
            {"action": "idle", "target": null, "reason": "rest"},
            {"action": "look_around", "target": null, "reason": "extra"}
          ],
          "reasoning": "Hungry but careful."
        }
        ```
        """,
        available_actions=AVAILABLE,
        max_steps=6,
    )

    assert parsed["reasoning"] == "Hungry but careful."
    assert parsed["plan_steps"] == [
        {"action": "smell", "target": None, "reason": "sample scent"},
        {"action": "go_to", "target": "SM_Fish_1", "reason": "approach"},
        {"action": "smell", "target": "SM_Fish_1", "reason": "confirm"},
        {"action": "eat", "target": "SM_Fish_1", "reason": "bite"},
        {"action": "sit", "target": None, "reason": "settle"},
        {"action": "idle", "target": None, "reason": "rest"},
    ]


def test_chosen_action_from_plan_builds_target_kwargs() -> None:
    chosen = chosen_action_from_plan([
        {"action": "go_to", "target": "SM_Fish_1", "reason": "approach"},
    ])

    assert chosen == {"action": "go_to", "kwargs": {"target": "SM_Fish_1"}}


def test_fast_mind_reasoning_keeps_slow_and_fast_context() -> None:
    reasoning = fast_mind_reasoning(
        {
            "intent": "EXPLORE",
            "style": "cautious sniff-first",
            "reasoning": "A stale place is available.",
        },
        [
            {"action": "smell", "target": None},
            {"action": "go_to", "target": "East_Roof"},
        ],
        "The body checks scent before moving.",
    )

    assert "A stale place is available." in reasoning
    assert "The body checks scent before moving." in reasoning
    assert "EXPLORE with a cautious sniff-first style" in reasoning
    assert "smell -> go_to:East_Roof" in reasoning
