from app.models import AgentWsRegisterMessage, AgentWsTickEnvelope


def test_register_message_cleans_duplicate_creature_ids():
    msg = AgentWsRegisterMessage.model_validate(
        {"type": "register", "creature_ids": ["cat_a", "cat_a", "", " cat_b "]}
    )

    assert msg.creature_ids == ["cat_a", "cat_b"]


def test_shared_tick_envelope_fills_creature_and_request_from_snapshot():
    msg = AgentWsTickEnvelope.model_validate(
        {
            "type": "tick",
            "snapshot": {
                "agent_id": "cat_a",
                "requestId": "req-001",
                "self": {"location": "dock", "current_action": "idle"},
            },
        }
    )

    assert msg.creature_id == "cat_a"
    assert msg.agent_id == "cat_a"
    assert msg.request_id == "req-001"


def test_shared_tick_envelope_prefers_top_level_agent_id():
    msg = AgentWsTickEnvelope.model_validate(
        {
            "type": "tick",
            "agent_id": "cat_top",
            "requestId": "req-top",
            "snapshot": {
                "agent_id": "cat_snapshot",
                "self": {"location": "dock", "current_action": "idle"},
            },
        }
    )

    assert msg.creature_id == "cat_top"
    assert msg.request_id == "req-top"
