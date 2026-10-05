from app.agent.mind.intent_arbitrator import select_intent_from_proposals


def test_explore_beats_social_on_single_soft_vote_tie() -> None:
    decision = select_intent_from_proposals([
        {"domain": "need", "intent": "IDLE"},
        {"domain": "exploration", "intent": "EXPLORE", "target_id": "East_Roof"},
        {"domain": "social", "intent": "SOCIALIZE", "target_id": "miso"},
    ])

    assert decision["intent"] == "EXPLORE"
    assert decision["target_id"] == "East_Roof"
    assert decision["source_domain"] == "exploration"


def test_social_still_wins_when_exploration_is_idle() -> None:
    decision = select_intent_from_proposals([
        {"domain": "need", "intent": "IDLE"},
        {"domain": "exploration", "intent": "IDLE"},
        {"domain": "social", "intent": "SOCIALIZE", "target_id": "miso"},
    ])

    assert decision["intent"] == "SOCIALIZE"
    assert decision["target_id"] == "miso"


def test_explore_beats_rest_for_demo_motion() -> None:
    decision = select_intent_from_proposals([
        {"domain": "need", "intent": "REST", "target_id": "warm_mat"},
        {"domain": "exploration", "intent": "EXPLORE", "target_id": "East_Roof"},
        {"domain": "social", "intent": "SOCIALIZE", "target_id": "miso"},
    ])

    assert decision["intent"] == "EXPLORE"
    assert decision["target_id"] == "East_Roof"


def test_social_beats_rest_when_exploration_is_idle() -> None:
    decision = select_intent_from_proposals([
        {"domain": "need", "intent": "REST", "target_id": "warm_mat"},
        {"domain": "exploration", "intent": "IDLE"},
        {"domain": "social", "intent": "SOCIALIZE", "target_id": "miso"},
    ])

    assert decision["intent"] == "SOCIALIZE"
    assert decision["target_id"] == "miso"
