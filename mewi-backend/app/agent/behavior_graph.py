from __future__ import annotations

import asyncio
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.arbitration import (
    propose_exploration_intent,
    propose_need_intent,
    propose_social_intent,
)
from app.agent.creature_runtime import CreatureRuntime, CreatureRuntimeState
from app.agent.intent_effects import execute_intent_effects as run_intent_effects
from app.agent.memory.memory_consolidate import build_turn_memory_write
from app.agent.memory.retrieval import build_langgraph_memory_state
from app.agent.mind.affordances import build_intent_affordances
from app.agent.mind.context_builder import build_structured_context
from app.agent.mind.intent_arbitrator import select_intent_from_proposals
from app.agent.schemas.perception_schema import PerceptionError
from app.agent.memory.place_memory_service import PlaceMemoryService
from app.social.service import SocialService
from app.world.state import WorldState


def _runtime(state: CreatureRuntimeState) -> CreatureRuntime:
    return state["runtime"]


def context_builder(state: CreatureRuntimeState) -> dict[str, Any]:
    """Node 1: clean Unity's snapshot into backend-owned context."""

    result = _runtime(state).perceive(state["raw_payload"])
    patch: dict[str, Any]
    if isinstance(result, PerceptionError):
        patch = {"perception": None, "perception_error": result.message}
    else:
        patch = {
            "perception": result.to_prompt_context(),
            "perception_error": None,
            "tick": result.tick,
        }
    patch["structured_context"] = build_structured_context({**state, **patch})
    return patch


def make_retrieve_memory(
    *,
    place_memory: PlaceMemoryService | None = None,
    world: WorldState | None = None,
    social: SocialService | None = None,
):
    """Node 2: retrieve recent, episodic, working, spatial, relationship memory."""

    async def retrieve_memory(state: CreatureRuntimeState) -> dict[str, Any]:
        raw = state.get("raw_payload", {}) or {}
        creature_id = state.get("creature_id", "") or ""
        structured = state.get("structured_context") or {}
        semantic_context = structured.get("semantic_context") or {}

        memory_context = _runtime(state).remember(last_n=5).to_prompt_context()
        longterm = await _runtime(state).memory.recall_longterm(
            _recall_query(structured, raw), creature_id=creature_id, limit=5
        )
        if longterm:
            memory_context = {**memory_context, "longterm": longterm}
        place_memory_context = await _retrieve_place_memory(place_memory, creature_id, raw)
        world_view = await _retrieve_world_view(world, creature_id, raw)
        social_context, dialogue = await _retrieve_relationship_context(social, creature_id)

        affordances = build_intent_affordances(
            raw,
            semantic_context=semantic_context,
            place_memory_context=place_memory_context,
            world_view=world_view,
        ).to_prompt_context()
        memory_state = build_langgraph_memory_state(
            memory_context=memory_context,
            place_memory_context=place_memory_context,
            world_view=world_view,
            social_context=social_context,
        )
        return {
            "memory_context": memory_context,
            "memory_state": memory_state,
            "place_memory_context": place_memory_context,
            "world_view": world_view,
            "social_context": social_context,
            "dialogue": dialogue,
            "intent_affordances": affordances,
        }

    return retrieve_memory


def make_call_domain_intents(llm):
    """Node 3: call the three domain proposal prompts in parallel."""

    async def call_domain_intents(state: CreatureRuntimeState) -> dict[str, Any]:
        calls = await asyncio.gather(
            propose_need_intent(llm, state),
            propose_exploration_intent(llm, state),
            propose_social_intent(llm, state),
        )
        proposals = [item["proposal"] for item in calls if item.get("proposal")]
        messages: list[Any] = []
        for item in calls:
            messages.extend(item.get("messages") or [])
        return {
            "domain_intents": proposals,
            "messages": messages,
        }

    return call_domain_intents


def select_intent(state: CreatureRuntimeState) -> dict[str, Any]:
    """Node 4: collapse domain proposals into one final intent."""

    proposals = [
        proposal
        for proposal in state.get("domain_intents", [])
        if isinstance(proposal, dict)
    ]
    decision = select_intent_from_proposals(proposals)
    return {
        "intent_proposals": proposals,
        "intent_decision": decision,
        "reasoning": _selection_summary(decision, proposals),
    }


def make_execute_intent_effects(social: SocialService | None = None):
    """Node 5: run deterministic backend effects needed by the chosen intent."""

    async def execute_intent_effects(state: CreatureRuntimeState) -> dict[str, Any]:
        return await run_intent_effects(state, social=social)

    return execute_intent_effects


def collect_response(state: CreatureRuntimeState) -> dict[str, Any]:
    """Node 6: final response assembly for Unity-facing fields."""

    proposals = [
        proposal
        for proposal in state.get("intent_proposals", [])
        if isinstance(proposal, dict)
    ]
    decision = state.get("intent_decision")
    reasoning = state.get("reasoning") or _selection_summary(decision, proposals)
    return {
        "chosen_action": None,
        "plan_steps": [],
        "action_result": None,
        "reasoning": reasoning,
    }


def make_reason(llm):
    """Backward-compatible alias for older imports/tests."""
    return make_call_domain_intents(llm)


async def _retrieve_place_memory(
    place_memory: PlaceMemoryService | None,
    creature_id: str,
    raw: dict[str, Any],
) -> dict[str, Any] | None:
    if place_memory is None:
        return None
    context = await place_memory.reflect_tick(creature_id, raw)
    return context.to_prompt_context()


async def _retrieve_world_view(
    world: WorldState | None,
    creature_id: str,
    raw: dict[str, Any],
) -> dict[str, Any] | None:
    if world is None:
        return None
    presence = await world.ingest_tick(creature_id, raw)
    snapshot = world.snapshot()
    peers = snapshot.cats_in_zone(presence.zone_id, exclude=creature_id)
    return {
        "self": presence.to_prompt_context(),
        "peers_in_zone": [peer.to_prompt_context() for peer in peers],
        "now": snapshot.now,
    }


async def _retrieve_relationship_context(
    social: SocialService | None,
    creature_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if social is None:
        return None, []
    result = await social.observe_turn(creature_id)
    return result.to_prompt_context(), result.dialogue_for_unity()


def _proposal_summary(proposals: list[dict[str, Any]]) -> str:
    if not proposals:
        return "No domain intent proposals were returned."
    parts = [
        f"{proposal.get('domain', 'unknown')}={proposal.get('intent', 'IDLE')}"
        for proposal in proposals
    ]
    return "Collected domain intent proposals: " + ", ".join(parts) + "."


def _selection_summary(decision: dict[str, Any] | None, proposals: list[dict[str, Any]]) -> str:
    if not isinstance(decision, dict):
        return _proposal_summary(proposals)
    intent = decision.get("intent", "IDLE")
    target = decision.get("target_id") or ""
    domains = decision.get("supporting_domains") or []
    suffix = f" for {target}" if target else ""
    if domains:
        return f"Selected {intent}{suffix} from {', '.join(domains)} proposal support."
    return f"Selected {intent}{suffix}."


async def persist_memory(state: CreatureRuntimeState) -> dict[str, Any]:
    """Node 7: write this turn to memory — hot STM now, durable store in the
    background — reviving the persistence the agent needs to learn over time."""
    runtime = _runtime(state)
    write = build_turn_memory_write(state)
    runtime.memory.persist_turn(write)
    return {"memory_write": write.to_prompt_context()}


def _recall_query(structured: dict[str, Any], raw: dict[str, Any]) -> str:
    """A short query for long-term recall: where the cat is + who's relevant."""
    parts: list[str] = []
    place_context = raw.get("place_context") if isinstance(raw.get("place_context"), dict) else {}
    current_zone = _clean_query_part(place_context.get("current_zone_id"))
    if current_zone:
        parts.append(current_zone)
    else:
        location = _clean_query_part((raw.get("self") or {}).get("location"))
        if location:
            parts.append(location)
    targets = (structured.get("semantic_context") or {}).get("relevant_targets") or []
    parts.extend(str(t).strip() for t in targets[:3] if str(t).strip())
    return " ".join(parts) or "recent activity"


def _clean_query_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(
            str(value.get(key)).strip()
            for key in ("x", "y", "z")
            if value.get(key) is not None and str(value.get(key)).strip()
        )
    return str(value).strip()


def build_behavior_graph(
    llm,
    place_memory: PlaceMemoryService | None = None,
    world: WorldState | None = None,
    social: SocialService | None = None,
) -> StateGraph:
    graph = StateGraph(CreatureRuntimeState)
    graph.add_node("context_builder", context_builder)
    graph.add_node("retrieve_memory", make_retrieve_memory(
        place_memory=place_memory,
        world=world,
        social=social,
    ))
    graph.add_node("call_domain_intents", make_call_domain_intents(llm))
    graph.add_node("select_intent", select_intent)
    graph.add_node("execute_intent_effects", make_execute_intent_effects(social))
    graph.add_node("collect_response", collect_response)
    graph.add_node("persist_memory", persist_memory)
    graph.set_entry_point("context_builder")
    graph.add_edge("context_builder", "retrieve_memory")
    graph.add_edge("retrieve_memory", "call_domain_intents")
    graph.add_edge("call_domain_intents", "select_intent")
    graph.add_edge("select_intent", "execute_intent_effects")
    graph.add_edge("execute_intent_effects", "collect_response")
    graph.add_edge("collect_response", "persist_memory")
    graph.add_edge("persist_memory", END)
    return graph
