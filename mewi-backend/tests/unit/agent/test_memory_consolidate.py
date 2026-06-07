from app.agent.creature_runtime import CreatureRuntime
from app.agent.memory.memory_consolidate import build_turn_memory_write


def test_turn_memory_write_captures_unity_result_and_python_plan() -> None:
    runtime = CreatureRuntime(persona="A careful test cat.")
    state = runtime.state_for_tick(
        "cat",
        {
            "requestId": "t0002",
            "agent_id": "cat",
            "self": {"location": "Bamboo_Boardwalk", "current_action": "idle"},
            "mood": {"fear": 0.1, "energy": 0.8, "curiosity": 0.7},
            "health": {"fullness": 0.1},
            "place_context": {
                "current_zone_id": "Bamboo_Boardwalk",
                "active_zone_ids": ["Harbor", "Bamboo_Boardwalk"],
            },
            "spatial_context": {
                "zones": [
                    {"id": "Harbor", "type": "district"},
                    {"id": "Bamboo_Boardwalk", "type": "path"},
                ],
            },
            "action_result": {
                "status": "completed",
                "steps": [
                    {
                        "action": "go_to",
                        "target": "SM_Fish_1",
                        "status": "completed",
                    },
                    {
                        "action": "eat",
                        "target": "SM_Fish_1",
                        "status": "completed",
                    },
                ],
            },
        },
    )
    state["intent_decision"] = {
        "intent": "SEEK_FOOD",
        "style": "cautious sniff-first",
        "reasoning": "Food is urgent.",
    }
    state["plan_steps"] = [
        {"action": "smell", "target": None, "reason": "sample scent"},
        {"action": "go_to", "target": "SM_Fish_1", "reason": "approach"},
        {"action": "eat", "target": "SM_Fish_1", "reason": "bite"},
    ]
    state["chosen_action"] = {"action": "smell", "kwargs": {}}

    write = build_turn_memory_write(state)
    runtime.memory.record_turn_memory(write)
    recall = runtime.memory.recall(last_n=5).to_prompt_context()

    assert write.raw_event.payload["previous_action_result"]["status"] == "completed"
    assert write.raw_event.payload["plan_steps"][1]["target"] == "SM_Fish_1"
    # STM intentionally keeps only cross-tick aspects ("action", and
    # "social" when present). The body / place / sensory blocks are rendered
    # fresh from the current snapshot, so echoing them into STM would be
    # pure duplication. See _build_aspect_memories.
    assert {memory.aspect for memory in write.aspect_memories} == {"action"} or \
        {memory.aspect for memory in write.aspect_memories} == {"action", "social"}
    assert runtime.memory.raw_event_count == 1
    assert any("Next intent SEEK_FOOD" in line for line in recall["short_term_lines"])


def test_turn_memory_remembers_words_said_and_heard_from_inbox() -> None:
    runtime = CreatureRuntime(persona="A chatty test cat.")
    state = runtime.state_for_tick(
        "cat_a",
        {
            "requestId": "t0003",
            "agent_id": "cat_a",
            "self": {"location": "Dock", "current_action": "idle"},
            "mood": {"social": 0.6},
            "health": {"fullness": 0.7},
        },
    )
    # What observe_turn delivered (heard) + what social_publish authored (said).
    state["social_context"] = {
        "delivered_inbox": [
            {"from": "cat_b", "text": "where did you find that fish?", "target": "cat_a"},
        ],
        "decision": {
            "spoke": True,
            "utterance": {"from": "cat_a", "text": "down by the crates", "target": "cat_b"},
        },
    }
    state["dialogue"] = [
        {"from": "cat_b", "text": "where did you find that fish?", "target": "cat_a"},
        {"from": "cat_a", "text": "down by the crates", "target": "cat_b"},
    ]

    write = build_turn_memory_write(state)
    runtime.memory.record_turn_memory(write)

    social = [m for m in write.aspect_memories if m.aspect == "social"]
    assert len(social) == 1
    assert 'You said to cat_b: "down by the crates"' in social[0].text
    assert 'Heard cat_b: "where did you find that fish?"' in social[0].text
    assert social[0].memory_kind == "episodic"

    # The raw event keeps the full conversation data in the Python backend.
    assert write.raw_event.payload["social_context"]["delivered_inbox"][0]["from"] == "cat_b"
    assert len(write.raw_event.payload["dialogue"]) == 2

    recall = runtime.memory.recall(last_n=5).to_prompt_context()
    assert any("down by the crates" in line for line in recall["short_term_lines"])
