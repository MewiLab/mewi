from app.agent.creature_runtime import CreatureRuntime
from app.agent.memory.summarizer import build_turn_memory_write


def test_turn_memory_write_captures_unity_result_and_python_plan() -> None:
    runtime = CreatureRuntime(persona="A careful test cat.")
    state = runtime.state_for_tick(
        "cat",
        {
            "requestId": "t0002",
            "agent_id": "cat",
            "self": {"location": "Bamboo_Boardwalk", "current_action": "idle"},
            "mood": {"fear": 0.1, "energy": 0.8, "curiosity": 0.7},
            "health": {"hunger": 0.9},
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
