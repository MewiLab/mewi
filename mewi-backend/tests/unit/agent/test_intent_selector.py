import json

from app.agent.mind.affordances import build_intent_affordances
from app.agent.mind.intent_selector import parse_intent_decision
from app.agent.prompts import format_intent_selection_prompt


def test_intent_prompt_receives_unity_affordances() -> None:
    affordances = build_intent_affordances({
        "available_intents": ["EXPLORE", "INVESTIGATE", "SEEK_FOOD", "SOCIALIZE", "REST", "SAFETY"],
        "targets": [
            {"id": "food_bowl_1", "supports": ["SEEK_FOOD"]},
            {"id": "cat_milo", "supports": ["SOCIALIZE", "INVESTIGATE"]},
            {"id": "garden_corner", "supports": ["EXPLORE"], "path_status": "safe", "path_length": 4.2},
        ],
    })

    prompt = format_intent_selection_prompt(
        temperament="curious",
        trust="unknown",
        semantic_context={
            "situation": "The cat is idle near the garden.",
            "body_lines": ["curiosity: curiosity is available"],
            "decision_focus": ["Choose a durable ActionFSM intent."],
        },
        intent_affordances=affordances,
    )

    assert "# ROLE: MEW (Intent Arbiter)" in prompt
    assert "# AVAILABLE INTENT AFFORDANCES" in prompt
    assert "available_intents: EXPLORE, INVESTIGATE, SEEK_FOOD, SOCIALIZE, REST, SAFETY" in prompt
    assert "garden_corner: supports EXPLORE; path safe, 4.2m" in prompt
    assert '"plan_steps"' not in prompt


def test_parse_intent_decision_returns_thin_directive() -> None:
    affordances = build_intent_affordances({
        "available_intents": ["EXPLORE", "SEEK_FOOD"],
        "targets": [{"id": "garden_corner", "supports": ["EXPLORE"]}],
    })

    parsed = parse_intent_decision(
        json.dumps({
            "intent": "EXPLORE",
            "target_id": "garden_corner",
            "mood": "curious",
            "style": "slow, sniffing path",
            "reasoning": "A fresh garden corner is available.",
        }),
        affordances=affordances,
    )

    assert parsed == {
        "intent": "EXPLORE",
        "target_id": "garden_corner",
        "mood": "curious",
        "style": "slow, sniffing path",
        "reasoning": "A fresh garden corner is available.",
    }


def test_parse_intent_decision_drops_target_that_does_not_support_intent() -> None:
    affordances = build_intent_affordances({
        "available_intents": ["EXPLORE", "SEEK_FOOD"],
        "targets": [{"id": "food_bowl_1", "supports": ["SEEK_FOOD"]}],
    })

    parsed = parse_intent_decision(
        json.dumps({
            "intent": "EXPLORE",
            "target_id": "food_bowl_1",
            "reasoning": "Bad target for this intent.",
        }),
        affordances=affordances,
    )

    assert parsed["intent"] == "EXPLORE"
    assert parsed["target_id"] == ""


def test_affordance_targets_infer_food_from_tags() -> None:
    affordances = build_intent_affordances({
        "available_intents": ["EXPLORE", "INVESTIGATE", "SEEK_FOOD"],
        "targets": [{"id": "fish", "tags": ["food.fish"]}],
    })

    assert affordances.targets[0].id == "fish"
    assert "SEEK_FOOD" in affordances.targets[0].supports
    assert affordances.target_supports_intent("fish", "SEEK_FOOD")
    assert not affordances.target_supports_intent("fish", "EXPLORE")


def test_reachable_routes_become_explore_fallback_targets() -> None:
    affordances = build_intent_affordances({
        "place_context": {"reachable_zone_ids": ["Boat_2", "House_4", "Blocked_9"]},
        "navigation_context": {
            "zone_routes": [
                {"id": "Boat_2", "status": "risky"},
                {"id": "House_4", "status": "safe"},
                {"id": "Blocked_9", "status": "blocked"},
            ],
        },
    })

    target_ids = affordances.target_ids()
    assert {"Boat_2", "House_4"} <= target_ids
    assert "Blocked_9" not in target_ids
    assert affordances.target_supports_intent("Boat_2", "EXPLORE")
    boat = next(target for target in affordances.targets if target.id == "Boat_2")
    assert boat.path_status == "risky"
