from app.agent.arbitration.social_proposal import (
    SOCIAL_ACT_KINDS,
    _finalize_social_act,
    build_communication_frame,
)


def _state_with_cues() -> dict:
    return {
        "structured_context": {
            "place": {"current_zone_id": "Bamboo_Boardwalk_1"},
            "navigation": {
                "zone_routes": [
                    {"id": "Sea_1", "status": "open"},
                    {"id": "Cliff_1", "status": "blocked"},
                ]
            },
            "signals": {"summary": "energy is low"},
            "semantic_context": {
                "relevant_targets": ["a fat silver mackerel", "a wooden crate"],
                "sensory_world": ["A sharp sea smell drifts in."],
            },
        },
        "social_context": {
            "delivered_inbox": [
                {"from": "kosto", "text": "Sea path smells sharp.", "kind": "share_cue"}
            ],
            "relationships": [
                {"pair": ["kosto", "miso"], "trust": 0.2, "affinity": 0.1, "encounters": 3}
            ],
        },
    }


def test_frame_distills_heard_place_route_food_and_relationship() -> None:
    frame = build_communication_frame(_state_with_cues())
    blob = "\n".join(frame)

    assert 'Heard from kosto (share_cue): "Sea path smells sharp."' in blob
    assert "current place is Bamboo_Boardwalk_1" in blob
    assert "Sea_1 is reachable" in blob
    assert "Cliff_1" not in blob  # blocked route is not sayable
    assert "a fat silver mackerel is nearby" in blob
    assert "energy is low" in blob
    assert "Relationship cue:" in blob


def test_frame_is_empty_without_cues() -> None:
    assert build_communication_frame({}) == []


def test_finalize_blanks_generic_say() -> None:
    proposal = {"social_act": {"kind": "greeting", "say": "mew?", "expects_reply": True}}
    _finalize_social_act(proposal, has_cue=True)

    assert proposal["social_act"]["say"] == ""
    assert proposal["social_act"]["expects_reply"] is False


def test_finalize_collapses_unknown_kind_to_message() -> None:
    proposal = {"social_act": {"kind": "banter", "say": "Fish smell is near the boxes."}}
    _finalize_social_act(proposal, has_cue=True)

    assert proposal["social_act"]["kind"] == "message"
    assert "message" in SOCIAL_ACT_KINDS
    assert proposal["social_act"]["say"] == "Fish smell is near the boxes."


def test_finalize_drops_bare_greeting_without_cue() -> None:
    proposal = {"social_act": {"kind": "greeting", "say": "Welcome over here.", "expects_reply": True}}
    _finalize_social_act(proposal, has_cue=False)

    assert proposal["social_act"]["say"] == ""
    assert proposal["social_act"]["expects_reply"] is False


def test_finalize_keeps_grounded_speech() -> None:
    proposal = {"social_act": {"kind": "invite", "say": "Sit here; the boardwalk is warm.", "expects_reply": True}}
    _finalize_social_act(proposal, has_cue=True)

    assert proposal["social_act"]["kind"] == "invite"
    assert proposal["social_act"]["say"] == "Sit here; the boardwalk is warm."
    assert proposal["social_act"]["expects_reply"] is True
