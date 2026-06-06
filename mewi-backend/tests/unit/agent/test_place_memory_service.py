from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage

from app.agent.schemas.place_memory_schema import PlaceMemoryEntry, PlaceMemoryOverlay
from app.agent.memory.place_memory_service import PlaceMemoryService


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[str] = []

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        self.calls.append(messages[0].content)
        return AIMessage(content=self.content)


class FakePlaceStore:
    def __init__(self) -> None:
        self.entries: dict[str, PlaceMemoryEntry] = {}
        self.recorded: list[str] = []
        self.summaries: list[dict[str, Any]] = []

    async def record_visit(
        self,
        creature_id: str,
        zone_id: str,
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        self.recorded.append(zone_id)
        current = self.entries.get(zone_id)
        visit_count = 1 if current is None else current.visit_count + 1
        self.entries[zone_id] = PlaceMemoryEntry(
            zone_id=zone_id,
            visit_count=visit_count,
            last_visited_at=observed_at,
            familiarity=min(1.0, visit_count / 8),
            last_arrival_request_id=request_id,
        )

    async def record_seen_places(
        self,
        creature_id: str,
        zone_ids: list[str],
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None:
        for zone_id in zone_ids:
            if zone_id in self.entries:
                continue
            self.entries[zone_id] = PlaceMemoryEntry(
                zone_id=zone_id,
                visit_count=0,
                last_seen_at=observed_at,
                last_arrival_request_id=request_id,
            )

    async def load_overlay(self, creature_id: str) -> PlaceMemoryOverlay:
        return PlaceMemoryOverlay(entries=dict(self.entries))

    async def record_place_summary(
        self,
        creature_id: str,
        zone_id: str,
        *,
        summary: str,
        evidence: dict[str, Any],
        observed_at: float,
        request_id: str = "",
    ) -> None:
        self.summaries.append({
            "creature_id": creature_id,
            "zone_id": zone_id,
            "summary": summary,
            "evidence": evidence,
            "request_id": request_id,
        })
        current = self.entries.get(zone_id) or PlaceMemoryEntry(zone_id=zone_id)
        self.entries[zone_id] = PlaceMemoryEntry(
            zone_id=zone_id,
            visit_count=current.visit_count,
            last_visited_at=current.last_visited_at,
            last_seen_at=current.last_seen_at,
            familiarity=current.familiarity,
            last_arrival_request_id=current.last_arrival_request_id,
            summary=summary,
            summary_updated_at=observed_at,
            summary_evidence=evidence,
        )


async def test_reflect_tick_records_deepest_zone() -> None:
    store = FakePlaceStore()
    service = PlaceMemoryService(store)

    context = await service.reflect_tick("cat", {
        "requestId": "t0001",
        "spatial_context": {
            "zones": [
                {"id": "Harbor", "type": "district"},
                {"id": "Bamboo_Boardwalk", "type": "path"},
            ],
        },
    })

    assert store.recorded == ["Bamboo_Boardwalk"]
    assert context.current_zone_id == "Bamboo_Boardwalk"
    assert any("Bamboo Boardwalk" in line for line in context.lines)


async def test_reflect_tick_scores_unvisited_reachable_zone() -> None:
    store = FakePlaceStore()
    service = PlaceMemoryService(store)

    context = await service.reflect_tick("cat", {
        "requestId": "t0002",
        "place_context": {
            "current_zone_id": "Bamboo_Boardwalk",
            "reachable_zone_ids": ["Bamboo_Boardwalk", "East_Roof", "Fishmonger_Stall"],
        },
    })

    assert context.best_exploration_target in {"East_Roof", "Fishmonger_Stall"}
    assert "East_Roof" in context.known_zone_ids
    assert any("target id:" in line for line in context.lines)
    assert any("Nearby but not visited yet" in line for line in context.lines)
    assert any("Known but not visited yet" in line for line in context.lines)


async def test_reflect_tick_without_zone_does_not_write() -> None:
    store = FakePlaceStore()
    service = PlaceMemoryService(store)

    context = await service.reflect_tick("cat", {"requestId": "t0003"})

    assert store.recorded == []
    assert context.current_zone_id == ""
    assert "quiet" in context.lines[0]


async def test_reflect_tick_schedules_place_llm_summary() -> None:
    store = FakePlaceStore()
    llm = FakeLLM("The cat was scratched by player_cat near the boat.")
    service = PlaceMemoryService(store, llm=llm)

    await service.reflect_tick("cat", {
        "requestId": "t0004",
        "tick": 4,
        "place_context": {"current_zone_id": "Boat_2"},
        "action_result": {
            "status": "observed",
            "events": [
                {
                    "actor_type": "player_cat",
                    "actor_id": "player_cat",
                    "target_type": "cat",
                    "target_id": "cat",
                    "action": "player_scratch",
                    "phase": "committed",
                }
            ],
        },
    })
    tasks = tuple(service._summary_tasks)
    assert tasks
    await asyncio.gather(*tasks)

    assert llm.calls
    assert "Boat 2" in llm.calls[0]
    assert "player_cat" in llm.calls[0]
    assert store.summaries[0]["zone_id"] == "Boat_2"
    assert store.entries["Boat_2"].summary == "The cat was scratched by player_cat near the boat."
