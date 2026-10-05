import json
from typing import Any

from langchain_core.messages import AIMessage

from app.agent.behavior_graph import build_behavior_graph
from app.agent.creature_runtime import CreatureRuntime
from app.social.service import SocialService
from app.world.state import WorldState


class StubLLM:
    """Intent selector fake that returns predictable JSON."""

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        return AIMessage(content=json.dumps({
            "intent": "SOCIALIZE",
            "target_id": None,
            "mood": "warm",
            "style": "soft chirps",
            "reasoning": "Another cat is nearby.",
        }))


class SpeakingLLM:
    """Intent selector picks SOCIALIZE with a target for Unity's FSM."""

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        return AIMessage(content=json.dumps({
            "intent": "SOCIALIZE",
            "target_id": "cat_b",
            "mood": "warm",
            "style": "soft chirps",
            "social_act": {
                "kind": "invite",
                "say": "come see this",
                "tone": "curious",
                "expects_reply": True,
            },
            "reasoning": "Another cat is nearby.",
        }))


class ExploreAndSpeakLLM:
    """Domain fake: body explores while the social proposal still speaks."""

    def __init__(self, *, social_target: str, say: str, kind: str = "invite") -> None:
        self.social_target = social_target
        self.say = say
        self.kind = kind

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        content = messages[0].content
        text = content if isinstance(content, str) else json.dumps(content)

        if "# ROLE: MEW Need Proposal" in text:
            return AIMessage(content=json.dumps({
                "intent": "IDLE",
                "target_id": None,
                "reasoning": "No body need is urgent.",
            }))
        if "# ROLE: MEW Exploration Proposal" in text:
            return AIMessage(content=json.dumps({
                "intent": "EXPLORE",
                "target_id": "East_Roof",
                "mood": "curious",
                "style": "trotting toward the route",
                "reasoning": "A reachable roof route is stale enough to inspect.",
            }))
        return AIMessage(content=json.dumps({
            "intent": "SOCIALIZE",
            "target_id": self.social_target,
            "mood": "bright",
            "style": "calling back without stopping",
            "social_act": {
                "kind": self.kind,
                "say": self.say,
                "tone": "curious",
                "expects_reply": self.kind != "reply",
            },
            "reasoning": "The social cue is worth answering while moving.",
        }))


def _payload(zone: str, agent_id: str, request_id: str, reachable: list[str] | None = None) -> dict:
    return {
        "requestId": request_id,
        "agent_id": agent_id,
        "self": {"location": {"x": 0.0, "y": 0.0, "z": 0.0}, "current_action": "idle"},
        "mood": {"social": 0.5, "fear": 0.1, "curiosity": 0.6, "energy": 0.6},
        "health": {"fullness": 0.7},
        "spatial_context": {"zones": [{"id": zone, "type": "district"}]},
        "place_context": {
            "current_zone_id": zone,
            "active_zone_ids": [zone],
            "reachable_zone_ids": reachable or [],
        },
        "entities": [],
    }


async def test_graph_retrieves_relationship_context_when_two_cats_share_zone() -> None:
    world = WorldState()
    social = SocialService(world=world)
    graph = build_behavior_graph(
        StubLLM(),
        world=world,
        social=social,
    ).compile()

    # Seed cat_b's presence so the room exists when cat_a ticks.
    await world.ingest_tick("cat_b", _payload("Harbor.Dock", "cat_b", "t0"))

    runtime_a = CreatureRuntime(persona="A friendly test cat.", creature_id="cat_a")
    result = await graph.ainvoke(
        runtime_a.state_for_tick("cat_a", _payload("Harbor.Dock", "cat_a", "t1")),
    )

    # World view recorded the peer in the same zone.
    peers = result["world_view"]["peers_in_zone"]
    assert [p["creature_id"] for p in peers] == ["cat_b"]

    social_ctx = result["social_context"]
    assert social_ctx["room"]["members"] == ["cat_a", "cat_b"]
    assert social_ctx["decision"]["note"] == "listening"

    assert result["dialogue"] == []
    assert result["intent_decision"]["intent"] == "SOCIALIZE"
    assert any(
        proposal["domain"] == "social" and proposal["intent"] == "SOCIALIZE"
        for proposal in result["intent_proposals"]
    )


async def test_graph_keeps_social_directive_thin() -> None:
    world = WorldState()
    social = SocialService(world=world)
    graph = build_behavior_graph(
        SpeakingLLM(),
        world=world,
        social=social,
    ).compile()

    await world.ingest_tick("cat_b", _payload("Harbor.Dock", "cat_b", "t0"))

    runtime_a = CreatureRuntime(persona="A chatty test cat.", creature_id="cat_a")
    result = await graph.ainvoke(
        runtime_a.state_for_tick("cat_a", _payload("Harbor.Dock", "cat_a", "t1")),
    )

    assert result["intent_decision"]["intent"] == "SOCIALIZE"
    assert result["intent_decision"]["target_id"] == "cat_b"
    social_proposal = next(item for item in result["intent_proposals"] if item["domain"] == "social")
    assert social_proposal["intent"] == "SOCIALIZE"
    assert social_proposal["target_id"] == "cat_b"
    assert result["plan_steps"] == []
    assert result["chosen_action"] is None
    assert result["social_context"]["decision"]["note"] == "agent_spoke"
    assert result["dialogue"][0]["from"] == "cat_a"
    assert result["dialogue"][0]["target"] == "cat_b"
    assert result["dialogue"][0]["text"] == "come see this"
    assert result["wake_targets"] == ["cat_b"]

    heard = await social.observe_turn("cat_b")
    assert [item.utterance.text for item in heard.delivered_inbox] == ["come see this"]


async def test_graph_can_explore_and_publish_social_side_channel() -> None:
    world = WorldState()
    social = SocialService(world=world)
    graph = build_behavior_graph(
        ExploreAndSpeakLLM(social_target="cat_b", say="come see the roof route"),
        world=world,
        social=social,
    ).compile()

    await world.ingest_tick("cat_b", _payload("Harbor.Dock", "cat_b", "t0"))

    runtime_a = CreatureRuntime(persona="A curious social test cat.", creature_id="cat_a")
    result = await graph.ainvoke(
        runtime_a.state_for_tick(
            "cat_a",
            _payload("Harbor.Dock", "cat_a", "t1", reachable=["East_Roof"]),
        ),
    )

    assert result["intent_decision"]["intent"] == "EXPLORE"
    assert result["intent_decision"]["target_id"] == "East_Roof"
    assert result["dialogue"][0]["from"] == "cat_a"
    assert result["dialogue"][0]["target"] == "cat_b"
    assert result["dialogue"][0]["text"] == "come see the roof route"
    assert result["wake_targets"] == ["cat_b"]

    heard = await social.observe_turn("cat_b")
    assert [item.utterance.text for item in heard.delivered_inbox] == ["come see the roof route"]


async def test_social_bid_can_be_replied_to_while_exploring() -> None:
    world = WorldState()
    social = SocialService(world=world)
    graph = build_behavior_graph(
        ExploreAndSpeakLLM(
            social_target="cat_a",
            say="I heard you; checking the roof first.",
            kind="reply",
        ),
        world=world,
        social=social,
    ).compile()

    await world.ingest_tick("cat_a", _payload("Harbor.Dock", "cat_a", "t0"))
    await world.ingest_tick("cat_b", _payload("Harbor.Dock", "cat_b", "t0"))
    await social.publish_turn("cat_a", say="come look", target="cat_b", expects_reply=True)

    runtime_b = CreatureRuntime(persona="A moving but responsive test cat.", creature_id="cat_b")
    result = await graph.ainvoke(
        runtime_b.state_for_tick(
            "cat_b",
            _payload("Harbor.Dock", "cat_b", "t1", reachable=["East_Roof"]),
        ),
    )

    assert result["intent_decision"]["intent"] == "EXPLORE"
    assert result["dialogue"][-1]["from"] == "cat_b"
    assert result["dialogue"][-1]["target"] == "cat_a"
    resolved = [item for item in result["social_effects"] if item.get("type") == "bid_resolved"]
    assert resolved and resolved[0]["status"] == "replied"

    feedback = await social.observe_turn("cat_a")
    assert feedback.social_feedback
    assert feedback.social_feedback[0].outcome == "replied"


async def test_graph_skips_social_when_cat_is_alone() -> None:
    world = WorldState()
    social = SocialService(world=world)
    graph = build_behavior_graph(
        StubLLM(),
        world=world,
        social=social,
    ).compile()

    runtime = CreatureRuntime(persona="A solo cat.", creature_id="cat_solo")
    result = await graph.ainvoke(
        runtime.state_for_tick("cat_solo", _payload("Empty_Yard", "cat_solo", "t1")),
    )

    assert result["world_view"]["peers_in_zone"] == []
    assert result["dialogue"] == []
    assert result["social_context"]["room"] is None
