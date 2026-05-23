from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.memory.summarizer import build_turn_memory_write
from app.agent.mind.fast import make_fast_mind
from app.agent.schemas.perception_schema import PerceptionError
from app.agent.mind.slow import make_slow_mind
from app.services.memory_service import MemoryService
from app.services.place_memory_service import PlaceMemoryService
from app.social.service import SocialService
from app.world.state import WorldState


def _runtime(state: CreatureRuntimeState) -> CreatureRuntime:
    return state["runtime"]


def perceive(state: CreatureRuntimeState) -> dict[str, Any]:
    result = _runtime(state).perceive(state["raw_payload"])
    if isinstance(result, PerceptionError):
        return {"perception": None, "perception_error": result.message}
    return {
        "perception": result.to_prompt_context(),
        "perception_error": None,
        "tick": result.tick,
    }


def remember(state: CreatureRuntimeState) -> dict[str, Any]:
    return {"memory_context": _runtime(state).remember(last_n=5).to_prompt_context()}


def make_ingest_world(world: WorldState | None = None):
    """Mirror this cat's snapshot into the shared WorldState before social/reflect runs."""

    async def ingest_world(state: CreatureRuntimeState) -> dict[str, Any]:
        if world is None:
            return {"world_view": None}

        creature_id = state.get("creature_id", "") or ""
        presence = await world.ingest_tick(creature_id, state.get("raw_payload", {}))
        snapshot = world.snapshot()
        peers = snapshot.cats_in_zone(presence.zone_id, exclude=creature_id)
        return {
            "world_view": {
                "self": presence.to_prompt_context(),
                "peers_in_zone": [peer.to_prompt_context() for peer in peers],
                "now": snapshot.now,
            },
        }

    return ingest_world


def make_reflect(place_memory: PlaceMemoryService | None = None):
    async def reflect(state: CreatureRuntimeState) -> dict[str, Any]:
        if place_memory is None:
            return {"place_memory_context": None}

        context = await place_memory.reflect_tick(
            state.get("creature_id", ""),
            state.get("raw_payload", {}),
        )
        return {"place_memory_context": context.to_prompt_context()}

    return reflect


def make_social_turn(social: SocialService | None = None):
    """Run the SocialRoom turn for this driver cat, if any peers share its zone."""

    async def social_turn(state: CreatureRuntimeState) -> dict[str, Any]:
        if social is None:
            return {"social_context": None, "dialogue": []}

        creature_id = state.get("creature_id", "") or ""
        result = await social.run_turn(creature_id)
        return {
            "social_context": result.to_prompt_context(),
            "dialogue": result.dialogue_for_unity(),
        }

    return social_turn


def make_reason(llm):
    """Backward-compatible alias for older imports/tests."""
    return make_slow_mind(llm)


def make_summarize_memory(memory_service: MemoryService | None = None):
    def summarize_memory_node(state: CreatureRuntimeState) -> dict[str, Any]:
        runtime = _runtime(state)
        write = build_turn_memory_write(state)
        if memory_service is None:
            runtime.memory.record_turn_memory(write)
        else:
            memory_service.record_turn_memory(runtime.memory, write)
        return {
            "memory_write": write.to_prompt_context(),
            "memory_context": runtime.remember(last_n=5).to_prompt_context(),
        }

    return summarize_memory_node


def summarize_memory(state: CreatureRuntimeState) -> dict[str, Any]:
    """Backward-compatible node for tests and older graph construction."""
    return make_summarize_memory()(state)


def build_behavior_graph(
    llm,
    place_memory: PlaceMemoryService | None = None,
    memory_service: MemoryService | None = None,
    world: WorldState | None = None,
    social: SocialService | None = None,
) -> StateGraph:
    graph = StateGraph(CreatureRuntimeState)
    graph.add_node("perceive", perceive)
    graph.add_node("remember", remember)
    graph.add_node("ingest_world", make_ingest_world(world))
    graph.add_node("reflect", make_reflect(place_memory))
    graph.add_node("social_turn", make_social_turn(social))
    graph.add_node("slow_mind", make_slow_mind(llm))
    graph.add_node("fast_mind", make_fast_mind(llm))
    graph.add_node("summarize_memory", make_summarize_memory(memory_service))
    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "remember")
    graph.add_edge("remember", "ingest_world")
    graph.add_edge("ingest_world", "reflect")
    graph.add_edge("reflect", "social_turn")
    graph.add_edge("social_turn", "slow_mind")
    graph.add_edge("slow_mind", "fast_mind")
    graph.add_edge("fast_mind", "summarize_memory")
    graph.add_edge("summarize_memory", END)
    return graph
