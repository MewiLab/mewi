import json
from typing import Any

from langchain_core.messages import AIMessage

from app.agent.behavior_graph import build_behavior_graph
from app.agent.creature_runtime import CreatureRuntime
from app.agent.schemas.place_memory_schema import PlaceMemoryEntry, PlaceMemoryOverlay
from app.services.place_memory_service import PlaceMemoryService


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        content = messages[0].content
        text = content if isinstance(content, str) else json.dumps(content)
        self.calls.append(text)
        if "# ROLE: MEW (Fast Mind)" in text:
            return AIMessage(content=json.dumps({
                "plan_steps": [
                    {
                        "action": "smell",
                        "target": None,
                        "reason": "sample the air before moving",
                    },
                    {
                        "action": "go_to",
                        "target": "East_Roof",
                        "reason": "explore a new or stale place",
                    },
                    {
                        "action": "smell",
                        "target": "East_Roof",
                        "reason": "read the new place by scent",
                    },
                    {
                        "action": "wander",
                        "target": None,
                        "reason": "pad around the edges",
                    },
                    {
                        "action": "sit",
                        "target": None,
                        "reason": "settle briefly and watch",
                    },
                ],
                "reasoning": "The sequence keeps the cat cautious while exploring.",
            }))
        return AIMessage(content=json.dumps({
            "intent": "EXPLORE",
            "target_id": None,
            "mood": "curious",
            "style": "cautious sniff-first",
            "reasoning": "The cat has energy and a stale place is available.",
        }))


class FakePlaceStore:
    def __init__(self) -> None:
        self.entries: dict[str, PlaceMemoryEntry] = {}

    async def record_visit(
        self,
        creature_id: str,
        zone_id: str,
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        self.entries[zone_id] = PlaceMemoryEntry(
            zone_id=zone_id,
            visit_count=1,
            last_visited_at=observed_at,
            last_arrival_request_id=request_id,
        )

    async def load_overlay(self, creature_id: str) -> PlaceMemoryOverlay:
        return PlaceMemoryOverlay(entries=dict(self.entries))


async def test_graph_reflects_place_then_fast_mind_builds_explore_plan() -> None:
    llm = FakeLLM()
    graph = build_behavior_graph(
        llm,
        place_memory=PlaceMemoryService(FakePlaceStore()),
    ).compile()
    runtime = CreatureRuntime(persona="A cautious test cat.")
    payload = {
        "requestId": "t0001",
        "agent_id": "cat",
        "self": {"location": {"x": 0, "y": 0, "z": 0}, "current_action": "idle"},
        "mood": {"curiosity": 0.8, "energy": 0.8, "fear": 0.1},
        "health": {"fullness": 0.9},
        "spatial_context": {
            "zones": [
                {"id": "Harbor", "type": "district"},
                {"id": "Bamboo_Boardwalk", "type": "path"},
            ],
        },
        "place_context": {
            "current_zone_id": "Bamboo_Boardwalk",
            "reachable_zone_ids": ["Bamboo_Boardwalk", "East_Roof"],
        },
        "entities": [],
    }

    result = await graph.ainvoke(runtime.state_for_tick("cat", payload))

    assert result["intent_decision"]["intent"] == "EXPLORE"
    assert result["place_memory_context"]["best_exploration_target"] == "East_Roof"
    assert result["intent_decision"]["style"] == "cautious sniff-first"
    assert result["plan_steps"][0]["action"] == "smell"
    assert result["plan_steps"][1] == {
        "action": "go_to",
        "target": "East_Roof",
        "reason": "explore a new or stale place",
    }
    assert result["chosen_action"] == {
        "action": "smell",
        "kwargs": {},
    }
    assert len(llm.calls) == 2
    assert "# ROLE: MEW (Slow Mind)" in llm.calls[0]
    assert "# ROLE: MEW (Fast Mind)" in llm.calls[1]
    assert result["memory_write"]["raw_event"]["event_type"] == "planning_turn"
    assert runtime.memory.raw_event_count == 1
    # STM intentionally keeps cross-tick facts only; body/place/sensory are
    # rendered from the current snapshot instead of being duplicated here.
    assert runtime.memory.short_term_count >= 1
    assert any(
        line.startswith("action:")
        for line in result["memory_context"]["short_term_lines"]
    )
