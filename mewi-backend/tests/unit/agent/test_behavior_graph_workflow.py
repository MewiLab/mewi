import json
from typing import Any

from langchain_core.messages import AIMessage

from app.agent.behavior_graph import build_behavior_graph
from app.agent.creature_runtime import CreatureRuntime
from app.agent.schemas.place_memory_schema import PlaceMemoryEntry, PlaceMemoryOverlay
from app.agent.memory.place_memory_service import PlaceMemoryService


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        content = messages[0].content
        text = content if isinstance(content, str) else json.dumps(content)
        self.calls.append(text)
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


async def test_graph_collects_parallel_domain_intents() -> None:
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

    assert result["place_memory_context"]["best_exploration_target"] == "East_Roof"
    assert result["memory_state"]["spatial"]["place_memory"]["best_exploration_target"] == "East_Roof"
    assert result["intent_decision"]["intent"] == "EXPLORE"
    assert result["intent_decision"]["confidence"] == "low"
    assert [item["domain"] for item in result["intent_proposals"]] == [
        "need",
        "exploration",
        "social",
    ]
    assert result["intent_proposals"][1]["intent"] == "EXPLORE"
    assert result["intent_proposals"][1]["style"] == "cautious sniff-first"
    assert result["plan_steps"] == []
    assert result["chosen_action"] is None
    assert result["tool_results"] == []
    assert len(llm.calls) == 3
    assert any("# ROLE: MEW Need Proposal" in call for call in llm.calls)
    assert any("# ROLE: MEW Exploration Proposal" in call for call in llm.calls)
    assert any("# ROLE: MEW Social Proposal" in call for call in llm.calls)
    assert all("# AVAILABLE INTENT AFFORDANCES" in call for call in llm.calls)
    assert all("# PERSONA" in call and "A cautious test cat." in call for call in llm.calls)
    assert all("# PROCESSED SNAPSHOT CONTEXT" in call for call in llm.calls)
    assert any("# MEMORY STATE" in call for call in llm.calls)
