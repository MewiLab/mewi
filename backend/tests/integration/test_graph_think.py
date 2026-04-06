"""
test_graph_think.py — Tests that the agent can actually *think* via the graph.

Validates the full cognitive loop:
    perceive (snapshot) → remember → reason (LLM) → act → reflect
                       ↘ error path → act(wait) → reflect

Two test tiers:

  1. MockLLM + MockUnityClient  (always runs, no network required)
     Tests every node and the full graph with a fake LLM that returns
     predictable JSON so we can assert on what action Unity receives.

  2. @pytest.mark.live — requires a running Unity game with AgentBridge.
     Auto-skipped if Unity is unreachable.  Run these while the game is open:

         pytest -m live backend/tests/integration/test_graph_think.py -v

"""

from __future__ import annotations

import json
import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from app.agent.graph import (
    build_creature_graph,
    make_perceive_node,
    make_remember_node,
    make_reason_node,
    make_act_node,
    make_reflect_node,
    route_after_perceive,
    route_after_reason,
)
from app.agent.schemas.state_schema import AgentGraphState
from app.agent.perception import SnapshotManager
from app.agent.memory import MemoryManager
from app.agent.action import ActionManager
from app.agent.creature_agent import CreatureAgent
from app.agent.unity_client import HttpUnityClient
from tests.mock_unity_client import MockUnityClient


# ─── Mock LLM ────────────────────────────────────────────────────────────────

class MockLLMProvider:
    """
    Fake LLM that returns a pre-set JSON decision.
    Lets us drive the reason node with controlled outputs.
    """

    def __init__(self, action: str = "move", kwargs: dict | None = None, reasoning: str = "test"):
        self._decision = {
            "action": action,
            "kwargs": kwargs or {},
            "reasoning": reasoning,
        }

    def invoke(self, messages: list[BaseMessage], **kw) -> BaseMessage:
        return AIMessage(content=json.dumps(self._decision))

    async def ainvoke(self, messages: list[BaseMessage], **kw) -> BaseMessage:
        return self.invoke(messages)

    def set_decision(self, action: str, kwargs: dict | None = None, reasoning: str = "") -> None:
        self._decision = {"action": action, "kwargs": kwargs or {}, "reasoning": reasoning}


class MalformedLLMProvider:
    """Returns garbage — tests the fallback path in make_reason_node."""

    def invoke(self, messages: list[BaseMessage], **kw) -> BaseMessage:
        return AIMessage(content="oops not json at all {{{")

    async def ainvoke(self, messages: list[BaseMessage], **kw) -> BaseMessage:
        return self.invoke(messages)


# ─── Shared fixture helpers ───────────────────────────────────────────────────

def _make_agent(extra_actions: list[str] | None = None) -> tuple[CreatureAgent, MockUnityClient]:
    """Return (agent, mock_client) wired together."""
    client = MockUnityClient()
    client.add_action("Sprint", "toggle", "Hold to run faster")
    client.add_action("Jump",   "press",  "Jump or climb surface")
    client.add_action("Attack1","press",  "Primary attack")
    for name in (extra_actions or []):
        client.add_action(name)

    eye    = SnapshotManager(relevance_radius=30.0, threat_radius=10.0)
    memory = MemoryManager(max_ticks=20)
    body   = ActionManager(client=client)
    agent  = CreatureAgent(eye=eye, memory=memory, body=body)
    return agent, client


def _unity_payload(
    creature_pos: tuple[float, float, float] = (10.0, 0.0, 5.0),
    creature_state: str = "Locomotion",
    entities: list[dict] | None = None,
    time_of_day: float = 12.0,
) -> dict[str, Any]:
    return {
        "environment_snapshot": {
            "time_of_day": time_of_day,
            "weather": "clear",
            "entities": entities or [],
        },
        "creature_snapshot": {
            "position": {"x": creature_pos[0], "y": creature_pos[1], "z": creature_pos[2]},
            "rotation_y": 0.0,
            "active_state": creature_state,
            "active_stance": "Default",
            "grounded": True,
            "speed": 1.0,
            "sprint": False,
        },
    }


def _entity(name: str, tag: str, pos: tuple[float, float, float]) -> dict:
    return {"name": name, "tag": tag, "position": {"x": pos[0], "y": pos[1], "z": pos[2]}, "distance": 0.0}


def _base_state(agent: CreatureAgent, payload: dict, *, tick: int = 0) -> AgentGraphState:
    """Minimal graph state with required fields populated."""
    return {
        "raw_payload":      payload,
        "perception":       None,
        "perception_error": None,
        "memory_context":   None,
        "chosen_action":    None,
        "reasoning":        None,
        "action_result":    None,
        "messages":         [],
        "tick":             tick,
        "available_actions": list(agent.body.available_actions),
    }


# ═════════════════════════════════════════════════════════════════════════════
#  1. Individual graph node unit tests (mock LLM + mock Unity, no network)
# ═════════════════════════════════════════════════════════════════════════════

class TestPerceiveNode:
    """make_perceive_node — snapshot in, perception dict out."""

    def test_valid_payload_populates_perception(self):
        agent, _ = _make_agent()
        node  = make_perceive_node(agent)
        state = _base_state(agent, _unity_payload())
        out   = node(state)

        assert out["perception_error"] is None
        assert out["perception"] is not None
        assert out["perception"]["threat_level"] == "safe"
        assert out["tick"] == 1

    def test_invalid_payload_sets_error(self):
        agent, _ = _make_agent()
        node  = make_perceive_node(agent)
        # Deliberately invalid: time_of_day must be a number
        bad   = {"environment_snapshot": {"time_of_day": "not-a-number"}}
        state = _base_state(agent, bad)
        out   = node(state)

        assert out["perception_error"] is not None
        assert out["perception"] is None

    def test_threat_danger_in_perception(self):
        agent, _ = _make_agent()
        node    = make_perceive_node(agent)
        payload = _unity_payload(
            creature_pos=(0, 0, 0),
            entities=[_entity("Wolf", "predator", (3, 0, 0))],  # 3 m < 10 m threat radius
        )
        state = _base_state(agent, payload)
        out   = node(state)

        assert out["perception"]["threat_level"] == "danger"

    def test_entity_count_correct(self):
        agent, _ = _make_agent()
        node = make_perceive_node(agent)
        payload = _unity_payload(
            creature_pos=(0, 0, 0),
            entities=[
                _entity("Rock", "obstacle", (5, 0, 0)),
                _entity("Tree", "obstacle", (8, 0, 0)),
            ],
        )
        out = node(_base_state(agent, payload))
        assert out["perception"]["entity_count"] == 2


class TestRememberNode:
    """make_remember_node — pulls from memory ring buffer."""

    def test_returns_memory_context(self):
        agent, _ = _make_agent()
        # Record a perception first so memory has something
        agent.perceive(_unity_payload())
        node  = make_remember_node(agent)
        state = _base_state(agent, _unity_payload())
        out   = node(state)

        ctx = out["memory_context"]
        assert ctx is not None
        assert "memory_ticks" in ctx

    def test_empty_memory_still_returns_context(self):
        agent, _ = _make_agent()
        node = make_remember_node(agent)
        out  = node(_base_state(agent, _unity_payload()))
        # Even empty memory produces a context dict
        assert "memory_ticks" in out["memory_context"]


class TestReasonNode:
    """make_reason_node — LLM decision, JSON parsing, fallback."""

    def test_returns_chosen_action_from_llm(self):
        agent, _ = _make_agent()
        llm  = MockLLMProvider(action="Jump", kwargs={"hold": 0.3}, reasoning="looks fun")
        node = make_reason_node(agent, llm)

        state = {**_base_state(agent, _unity_payload()),
                 "perception": {"threat_level": "safe"},
                 "memory_context": {"memory_ticks": 0}}
        out = node(state)

        assert out["chosen_action"]["action"] == "Jump"
        assert out["chosen_action"]["kwargs"]["hold"] == 0.3
        assert out["reasoning"] == "looks fun"

    def test_malformed_llm_falls_back_to_wait(self):
        agent, _ = _make_agent()
        node = make_reason_node(agent, MalformedLLMProvider())

        state = {**_base_state(agent, _unity_payload()),
                 "perception": {},
                 "memory_context": {}}
        out = node(state)

        assert out["chosen_action"]["action"] == "wait"
        assert "failed" in out["reasoning"].lower()

    def test_llm_code_fence_stripped(self):
        """LLMs often wrap JSON in ```json ... ``` — node must handle it."""
        agent, _ = _make_agent()

        class FencedLLM:
            def invoke(self, messages, **kw):
                body = json.dumps({"action": "Sprint", "kwargs": {}, "reasoning": "go fast"})
                return AIMessage(content=f"```json\n{body}\n```")
            async def ainvoke(self, messages, **kw):
                return self.invoke(messages)

        node = make_reason_node(agent, FencedLLM())
        state = {**_base_state(agent, _unity_payload()), "perception": {}, "memory_context": {}}
        out = node(state)

        assert out["chosen_action"]["action"] == "Sprint"

    def test_messages_appended(self):
        agent, _ = _make_agent()
        llm  = MockLLMProvider(action="move")
        node = make_reason_node(agent, llm)

        state = {**_base_state(agent, _unity_payload()),
                 "perception": {}, "memory_context": {}}
        out = node(state)

        assert len(out["messages"]) >= 2  # HumanMessage + AIMessage


class TestActNode:
    """make_act_node — executes chosen_action via agent.body."""

    @pytest.mark.asyncio
    async def test_executes_known_action(self):
        agent, client = _make_agent()
        await agent.connect()
        node = make_act_node(agent)

        state = {**_base_state(agent, _unity_payload()),
                 "chosen_action": {"action": "Jump", "kwargs": {"hold": 0.2}}}
        out = await node(state)

        assert out["action_result"]["success"] is True
        assert out["action_result"]["action"] == "Jump"
        assert client.last_action["action"] == "Jump"

    @pytest.mark.asyncio
    async def test_wait_action_skips_unity_call(self):
        agent, client = _make_agent()
        await agent.connect()
        node = make_act_node(agent)

        state = {**_base_state(agent, _unity_payload()),
                 "chosen_action": {"action": "wait", "kwargs": {}}}
        out = await node(state)

        assert out["action_result"]["success"] is True
        assert len(client.action_log) == 0  # nothing sent to Unity

    @pytest.mark.asyncio
    async def test_no_chosen_action_defaults_to_wait(self):
        agent, client = _make_agent()
        await agent.connect()
        node  = make_act_node(agent)
        state = {**_base_state(agent, _unity_payload()), "chosen_action": None}
        out   = await node(state)

        assert out["action_result"]["action"] == "wait"
        assert len(client.action_log) == 0

    @pytest.mark.asyncio
    async def test_move_sends_axis_values(self):
        agent, client = _make_agent()
        await agent.connect()
        node = make_act_node(agent)

        state = {**_base_state(agent, _unity_payload()),
                 "chosen_action": {"action": "move", "kwargs": {"x": 0.0, "y": 1.0, "hold": 0.3}}}
        out = await node(state)

        assert out["action_result"]["success"] is True
        assert client.last_action["action"] == "move"
        assert client.last_action["y"] == 1.0  # body maps z→y for Unity wire format


class TestReflectNode:
    """make_reflect_node — summarises outcome into message history."""

    def test_appends_reflection_message(self):
        agent, _ = _make_agent()
        node = make_reflect_node(agent)

        state = {**_base_state(agent, _unity_payload()),
                 "action_result": {"success": True, "action": "Sprint", "detail": ""},
                 "reasoning": "ran away from wolf"}
        out = node(state)

        assert len(out["messages"]) == 1
        content = out["messages"][0].content
        assert "Sprint" in content
        assert "True" in content

    def test_reflection_includes_failure(self):
        agent, _ = _make_agent()
        node = make_reflect_node(agent)

        state = {**_base_state(agent, _unity_payload()),
                 "action_result": {"success": False, "action": "FlyAway", "detail": "unknown"},
                 "reasoning": "desperate"}
        out = node(state)

        assert "False" in out["messages"][0].content


class TestRouting:
    """Edge routing functions."""

    def test_route_after_perceive_ok(self):
        agent, _ = _make_agent()
        state = {**_base_state(agent, _unity_payload()), "perception_error": None}
        assert route_after_perceive(state) == "remember"

    def test_route_after_perceive_error(self):
        agent, _ = _make_agent()
        state = {**_base_state(agent, _unity_payload()), "perception_error": "boom"}
        assert route_after_perceive(state) == "act"

    def test_route_after_reason_wait_ends(self):
        from langgraph.graph import END
        agent, _ = _make_agent()
        state = {**_base_state(agent, _unity_payload()),
                 "chosen_action": {"action": "wait"}}
        assert route_after_reason(state) == END

    def test_route_after_reason_act_continues(self):
        agent, _ = _make_agent()
        state = {**_base_state(agent, _unity_payload()),
                 "chosen_action": {"action": "Jump"}}
        assert route_after_reason(state) == "act"


# ═════════════════════════════════════════════════════════════════════════════
#  2. Full graph integration tests (mock LLM + mock Unity, no network)
# ═════════════════════════════════════════════════════════════════════════════

class TestFullGraphThink:
    """
    Runs build_creature_graph().compile().ainvoke(...) end-to-end.

    Mock LLM returns a controlled decision → graph routes through all nodes
    → we assert on what ended up in Unity's action log.
    """

    async def _run_graph(
        self,
        llm,
        payload: dict,
        extra_actions: list[str] | None = None,
    ) -> tuple[dict, MockUnityClient]:
        agent, client = _make_agent(extra_actions)
        await agent.connect()

        compiled = build_creature_graph(agent, llm).compile()
        state: AgentGraphState = {
            "raw_payload":       payload,
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "messages":          [],
            "tick":              0,
            "available_actions": list(agent.body.available_actions),
        }
        final = await compiled.ainvoke(state)
        return final, client

    @pytest.mark.asyncio
    async def test_graph_jump_action_reaches_unity(self):
        llm   = MockLLMProvider(action="Jump", kwargs={"hold": 0.25}, reasoning="hop over obstacle")
        final, client = await self._run_graph(llm, _unity_payload())

        assert client.last_action["action"] == "Jump"
        assert client.last_action["hold"] == 0.25

    @pytest.mark.asyncio
    async def test_graph_sprint_action_reaches_unity(self):
        llm   = MockLLMProvider(action="Sprint", kwargs={}, reasoning="flee")
        final, client = await self._run_graph(llm, _unity_payload())

        assert client.last_action["action"] == "Sprint"

    @pytest.mark.asyncio
    async def test_graph_move_forward_reaches_unity(self):
        llm   = MockLLMProvider(action="move", kwargs={"x": 0.0, "z": 1.0, "hold": 0.4})
        final, client = await self._run_graph(llm, _unity_payload())

        assert client.last_action["action"] == "move"
        assert client.last_action["y"] == 1.0

    @pytest.mark.asyncio
    async def test_graph_wait_ends_early_no_unity_call(self):
        """LLM decides 'wait' → route_after_reason sends to END, Unity never called."""
        llm   = MockLLMProvider(action="wait", reasoning="nothing to do")
        final, client = await self._run_graph(llm, _unity_payload())

        assert len(client.action_log) == 0
        assert final.get("chosen_action", {}).get("action") == "wait"

    @pytest.mark.asyncio
    async def test_graph_bad_snapshot_emits_wait_action(self):
        """
        Perception error → route_after_perceive → act (no chosen_action) → wait.
        Unity still receives nothing.
        """
        llm = MockLLMProvider(action="Jump")
        bad_payload = {"environment_snapshot": {"time_of_day": "NaN_string"}}
        final, client = await self._run_graph(llm, bad_payload)

        assert final["perception_error"] is not None
        assert len(client.action_log) == 0

    @pytest.mark.asyncio
    async def test_graph_malformed_llm_defaults_to_wait(self):
        """Unparseable LLM output → fallback wait → no Unity call."""
        final, client = await self._run_graph(MalformedLLMProvider(), _unity_payload())

        assert final.get("chosen_action", {}).get("action") == "wait"
        assert len(client.action_log) == 0

    @pytest.mark.asyncio
    async def test_graph_perception_danger_in_state(self):
        """With a predator nearby the graph state should carry threat_level=danger."""
        payload = _unity_payload(
            creature_pos=(0, 0, 0),
            entities=[_entity("Wolf", "predator", (4, 0, 0))],
        )
        llm   = MockLLMProvider(action="Sprint", reasoning="predator at 4m, flee!")
        final, client = await self._run_graph(llm, payload)

        assert final["perception"]["threat_level"] == "danger"
        assert client.last_action["action"] == "Sprint"

    @pytest.mark.asyncio
    async def test_graph_multiple_ticks_accumulate_memory(self):
        """
        Run the graph twice — second tick should have memory from the first.
        Both ticks emit actions; client log grows.
        """
        agent, client = _make_agent()
        await agent.connect()

        llm_jump   = MockLLMProvider(action="Jump")
        llm_sprint = MockLLMProvider(action="Sprint")

        base_state: AgentGraphState = {
            "raw_payload":       _unity_payload(creature_pos=(0, 0, 0)),
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "messages":          [],
            "tick":              0,
            "available_actions": list(agent.body.available_actions),
        }

        # Tick 1
        g1 = build_creature_graph(agent, llm_jump).compile()
        await g1.ainvoke({**base_state, "raw_payload": _unity_payload(creature_pos=(0, 0, 0))})

        # Tick 2 — agent.memory now has tick 1
        g2 = build_creature_graph(agent, llm_sprint).compile()
        await g2.ainvoke({**base_state, "raw_payload": _unity_payload(creature_pos=(5, 0, 0))})

        assert agent.memory.tick_count == 2
        actions = [a["action"] for a in client.action_log]
        assert "Jump" in actions
        assert "Sprint" in actions

    @pytest.mark.asyncio
    async def test_graph_action_result_in_final_state(self):
        """action_result should be populated at the end of a successful tick."""
        llm   = MockLLMProvider(action="Jump")
        final, _ = await self._run_graph(llm, _unity_payload())

        result = final.get("action_result")
        assert result is not None
        assert result["success"] is True
        assert result["action"] == "Jump"

    @pytest.mark.asyncio
    async def test_graph_reflect_message_in_final_state(self):
        """Reflect node appends a summary message — should appear in messages list."""
        llm   = MockLLMProvider(action="Jump", reasoning="because jump")
        final, _ = await self._run_graph(llm, _unity_payload())

        # messages from reason + reflect
        contents = [m.content for m in final["messages"]]
        assert any("[Reflection]" in c for c in contents)


# ═════════════════════════════════════════════════════════════════════════════
#  3. Live Unity integration tests  (@pytest.mark.live)
#
#  These run ONLY if Unity's AgentBridge is reachable at localhost:8080.
#  Skip automatically when the game is closed.
#
#  Run manually:
#      pytest -m live backend/tests/integration/test_graph_think.py -v -s
# ═════════════════════════════════════════════════════════════════════════════

async def _unity_is_live(url: str = "http://localhost:8080") -> bool:
    """Return True if AgentBridge responds to /ping."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=1.0) as c:
            r = await c.get(f"{url}/ping")
            return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


@pytest.mark.live
class TestLiveGraphThink:
    """
    Full graph tick against a running Unity game.

    Auto-skips if Unity is not reachable.  Each test:
      1. Connects to AgentBridge and fetches real game state.
      2. Runs the full graph with a MockLLM so we pick the action deterministically.
      3. Asserts Unity acknowledged the action.
    """

    UNITY_URL = "http://localhost:8080"

    @pytest.fixture(autouse=True)
    async def require_unity(self):
        if not await _unity_is_live(self.UNITY_URL):
            pytest.skip("Unity AgentBridge not reachable — open the game first.")

    async def _run_live_graph(self, action: str, kwargs: dict | None = None) -> tuple[dict, HttpUnityClient]:
        client = HttpUnityClient(base_url=self.UNITY_URL, timeout=3.0)
        eye    = SnapshotManager(relevance_radius=30.0, threat_radius=10.0)
        memory = MemoryManager(max_ticks=50)
        body   = ActionManager(client=client)
        agent  = CreatureAgent(eye=eye, memory=memory, body=body)

        connected = await agent.connect()
        assert connected, "AgentBridge connected but agent.connect() returned False"

        # Get real game state to build a realistic payload
        raw_state = await client.get_state()
        payload = {
            "creature_snapshot": {
                "position":      {"x": raw_state.get("posX", 0), "y": raw_state.get("posY", 0), "z": raw_state.get("posZ", 0)},
                "rotation_y":    raw_state.get("rotY", 0),
                "active_state":  raw_state.get("activeState", "none"),
                "active_stance": raw_state.get("activeStance", "none"),
                "grounded":      raw_state.get("grounded", True),
                "speed":         raw_state.get("speed", 0),
                "sprint":        raw_state.get("sprint", False),
            },
            "environment_snapshot": {
                "time_of_day": 12.0,
                "weather":     "clear",
                "entities":    [],
            },
        }

        llm   = MockLLMProvider(action=action, kwargs=kwargs or {}, reasoning="live test")
        state: AgentGraphState = {
            "raw_payload":       payload,
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "messages":          [],
            "tick":              0,
            "available_actions": list(agent.body.available_actions),
        }
        compiled = build_creature_graph(agent, llm).compile()
        final    = await compiled.ainvoke(state)
        await agent.disconnect()
        return final, client

    @pytest.mark.asyncio
    async def test_live_graph_perceives_real_snapshot(self):
        """
        Graph successfully perceives real Unity state (no perception_error).
        """
        final, _ = await self._run_live_graph("wait")
        assert final.get("perception_error") is None, (
            f"Perception failed on real state: {final.get('perception_error')}"
        )
        assert final["perception"] is not None
        # Creature snapshot must have position keys
        assert "creature" in final["perception"]

    @pytest.mark.asyncio
    async def test_live_graph_sends_move_to_unity(self):
        """
        Graph sends a move-forward action to the live game and Unity confirms it.
        """
        final, _ = await self._run_live_graph("move", {"x": 0.0, "z": 1.0, "hold": 0.3})

        result = final.get("action_result", {})
        assert result.get("success") is True, (
            f"Move action failed: {result.get('detail')}"
        )

    @pytest.mark.asyncio
    async def test_live_graph_sends_stop_to_unity(self):
        """Graph can halt the creature via the full cognitive loop."""
        final, _ = await self._run_live_graph("stop")

        result = final.get("action_result", {})
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_live_graph_available_actions_from_bridge(self):
        """
        Actions registered in AgentBridge.cs are visible in graph state.
        At minimum 'move', 'stop', 'wait' must be present.
        """
        final, _ = await self._run_live_graph("wait")
        actions = set(final["available_actions"])
        assert "move" in actions
        assert "stop" in actions

    @pytest.mark.asyncio
    async def test_live_graph_full_tick_jump(self):
        """
        End-to-end: perceive real snapshot → reason(mock→Jump) → send Jump to Unity.
        """
        final, _ = await self._run_live_graph("Jump", {"hold": 0.2})

        result = final.get("action_result", {})
        assert result.get("action") == "Jump", (
            f"Expected Jump, got: {result.get('action')}"
        )
        assert result.get("success") is True


# ═════════════════════════════════════════════════════════════════════════════
#  4. @pytest.mark.paid — Real LLM thinks, MockUnityClient receives
#
#  Uses the real LLM configured in .env (LLM_PROVIDER / LLM_MODEL / LLM_API_KEY).
#  No Unity required — the mock client records what the LLM decided.
#
#  Run:
#      pytest -m paid backend/tests/integration/test_graph_think.py -v -s
# ═════════════════════════════════════════════════════════════════════════════

# AgentBridge.cs hard-wires these three; button names come from MInputLink.
_AGENTBRIDGE_BUILTIN_ACTIONS: frozenset[str] = frozenset({"move", "stop", "wait"})

# Button names AgentBridge.cs exposes through MInputLink (cat rig defaults).
# Tests that assert "a specific button fires" should be from this list.
_AGENTBRIDGE_BUTTON_ACTIONS: frozenset[str] = frozenset({
    "Sprint", "Jump", "Attack1",
})

# Union — everything AgentBridge.cs will accept without a 404.
_ALL_AGENTBRIDGE_ACTIONS: frozenset[str] = (
    _AGENTBRIDGE_BUILTIN_ACTIONS | _AGENTBRIDGE_BUTTON_ACTIONS
)


def _make_paid_agent() -> tuple[CreatureAgent, MockUnityClient]:
    """Agent wired with the full AgentBridge action set."""
    client = MockUnityClient()
    for name in _AGENTBRIDGE_BUTTON_ACTIONS:
        client.add_action(name)
    eye    = SnapshotManager(relevance_radius=30.0, threat_radius=10.0)
    memory = MemoryManager(max_ticks=50)
    body   = ActionManager(client=client)
    agent  = CreatureAgent(eye=eye, memory=memory, body=body)
    return agent, client


def _real_llm():
    """Load the LLM configured in .env — the same one the app uses."""
    from app.agent.llm_provider import create_llm_provider
    return create_llm_provider()


def _scenario_payload(
    creature_pos: tuple[float, float, float] = (10.0, 0.0, 5.0),
    state: str = "Locomotion",
    entities: list[dict] | None = None,
) -> dict:
    return _unity_payload(creature_pos=creature_pos, creature_state=state, entities=entities)


@pytest.mark.paid
class TestPaidLLMThink:
    """
    Real LLM + MockUnityClient.

    Each test crafts a scenario payload, runs the full graph, and asserts:
      1. The LLM produced a valid AgentBridge action (not a hallucination).
      2. The chosen_action kwargs are structurally correct for that action type.
      3. The reasoning field is non-empty (LLM actually reflected).
      4. The MockUnityClient received the correct wire-format call.
    """

    async def _run(self, payload: dict) -> tuple[dict, MockUnityClient]:
        agent, client = _make_paid_agent()
        await agent.connect()
        llm = _real_llm()

        state: AgentGraphState = {
            "raw_payload":       payload,
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "messages":          [],
            "tick":              0,
            "available_actions": list(agent.body.available_actions),
        }
        compiled = build_creature_graph(agent, llm).compile()
        final    = await compiled.ainvoke(state)
        await agent.disconnect()
        return final, client

    # ── helpers ───────────────────────────────────────────────────────────────

    def _assert_valid_agentbridge_action(self, final: dict) -> str:
        """
        Assert chosen_action is a real AgentBridge action and return its name.
        Also validates move kwargs if the LLM chose 'move'.
        """
        chosen = final.get("chosen_action") or {}
        action = chosen.get("action", "")

        assert action, "LLM returned an empty action name"
        assert action in _ALL_AGENTBRIDGE_ACTIONS, (
            f"LLM hallucinated action '{action}' — not in AgentBridge.cs. "
            f"Valid: {sorted(_ALL_AGENTBRIDGE_ACTIONS)}"
        )

        if action == "move":
            kwargs = chosen.get("kwargs", {})
            # x/y must be floats in [-1, 1], hold must be positive
            if "x" in kwargs:
                assert -1.0 <= float(kwargs["x"]) <= 1.0, f"move.x out of range: {kwargs['x']}"
            if "z" in kwargs or "y" in kwargs:
                forward = kwargs.get("z", kwargs.get("y", 0))
                assert -1.0 <= float(forward) <= 1.0, f"move forward axis out of range: {forward}"
            if "hold" in kwargs:
                assert float(kwargs["hold"]) > 0, f"move hold must be > 0: {kwargs['hold']}"

        return action

    # ── scenario tests ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_open_field_llm_picks_valid_action(self):
        """
        Idle cat in an open field — LLM should choose any valid AgentBridge action.
        Baseline: no hallucinations, well-formed JSON.
        """
        payload = _scenario_payload(creature_pos=(0, 0, 0), state="Idle")
        final, client = await self._run(payload)

        action = self._assert_valid_agentbridge_action(final)
        assert final.get("reasoning"), "LLM must provide reasoning"

        # If it chose to act (not wait), Unity should have received it
        if action not in ("wait",):
            assert client.last_action is not None, (
                f"LLM chose '{action}' but nothing was sent to Unity"
            )

    @pytest.mark.asyncio
    async def test_walk_scenario_llm_uses_move_action(self):
        """
        Cat is idle, no threats, open terrain — LLM should explore by moving.
        We assert the chosen action is valid; if it's 'move' we verify the
        Unity wire format has a forward axis (y > 0 in AgentBridge coordinates).
        """
        payload = _scenario_payload(
            creature_pos=(0, 0, 0),
            state="Idle",
            entities=[_entity("FoodBowl", "food", (15, 0, 0))],
        )
        final, client = await self._run(payload)

        action = self._assert_valid_agentbridge_action(final)
        assert final.get("reasoning"), "LLM must explain why it chose to walk"

        if action == "move":
            sent = client.last_action
            assert sent is not None
            assert sent["action"] == "move"
            # AgentBridge.cs: y = forward/back axis
            assert sent.get("y", 0) != 0 or sent.get("x", 0) != 0, (
                "move action sent zero axes — creature would not move"
            )

    @pytest.mark.asyncio
    async def test_sprint_scenario_llm_picks_evasive_action(self):
        """
        Predator 4 m away (within threat_radius=10) → threat_level=DANGER.
        The LLM should pick Sprint, move (flee), stop, or wait — never a made-up action.
        """
        payload = _scenario_payload(
            creature_pos=(0, 0, 0),
            state="Locomotion",
            entities=[_entity("Wolf", "predator", (4, 0, 0))],
        )
        final, client = await self._run(payload)

        assert final["perception"]["threat_level"] == "danger"
        action = self._assert_valid_agentbridge_action(final)

        # LLM saw DANGER — it must have produced reasoning about the threat
        reasoning = final.get("reasoning", "")
        assert reasoning, "LLM must reason about the threat"

    @pytest.mark.asyncio
    async def test_jump_scenario_llm_picks_valid_action(self):
        """
        Cat at the base of a raised platform — Jump is available.
        The LLM should not hallucinate 'climb' or 'vault'; only AgentBridge actions.
        """
        payload = _scenario_payload(
            creature_pos=(0, 0, 0),
            state="Idle",
            entities=[_entity("Platform", "obstacle", (3, 2, 0))],
        )
        final, _ = await self._run(payload)

        action = self._assert_valid_agentbridge_action(final)
        # Jump is available in our mock; if LLM wants to climb it should choose Jump
        assert action in _ALL_AGENTBRIDGE_ACTIONS

    @pytest.mark.asyncio
    async def test_attack_scenario_llm_picks_valid_action(self):
        """
        Hostile entity at close range while cat is in Locomotion.
        Attack1 is available — LLM may or may not choose it, but must stay
        within AgentBridge's action vocabulary.
        """
        payload = _scenario_payload(
            creature_pos=(0, 0, 0),
            state="Locomotion",
            entities=[_entity("Rat", "prey", (2, 0, 0))],
        )
        final, _ = await self._run(payload)
        self._assert_valid_agentbridge_action(final)

    @pytest.mark.asyncio
    async def test_full_graph_move_wire_format_agentbridge_compatible(self):
        """
        When the LLM decides to move, verify the payload sent to Unity exactly
        matches what AgentBridge.cs expects:
            POST /action {"action": "move", "hold": <float>, "x": <float>, "y": <float>}
        """
        payload = _scenario_payload(
            creature_pos=(0, 0, 0),
            state="Idle",
            entities=[_entity("FoodBowl", "food", (20, 0, 0))],
        )
        final, client = await self._run(payload)

        if final.get("chosen_action", {}).get("action") == "move":
            sent = client.last_action
            assert sent is not None
            assert sent["action"] == "move"
            # AgentBridge.cs only reads: action, hold, x, y
            assert "hold" in sent, "AgentBridge needs 'hold' to set _moveTimer"
            assert "x"    in sent, "AgentBridge needs 'x' for strafe axis"
            assert "y"    in sent, "AgentBridge needs 'y' for forward/back axis"

    @pytest.mark.asyncio
    async def test_multiple_ticks_llm_memory_context_grows(self):
        """
        Two consecutive ticks with real LLM.
        On the second tick the reason node receives memory from tick 1 —
        the LLM must still return a valid action (memory context doesn't confuse it).
        """
        agent, client = _make_paid_agent()
        await agent.connect()
        llm = _real_llm()

        base_state: AgentGraphState = {
            "raw_payload":       {},
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "messages":          [],
            "tick":              0,
            "available_actions": list(agent.body.available_actions),
        }

        # Tick 1 — open field
        g = build_creature_graph(agent, llm).compile()
        s1 = {**base_state, "raw_payload": _scenario_payload(creature_pos=(0, 0, 0))}
        f1 = await g.ainvoke(s1)
        action1 = (f1.get("chosen_action") or {}).get("action", "")
        assert action1 in _ALL_AGENTBRIDGE_ACTIONS, f"Tick 1 hallucination: {action1!r}"

        # Tick 2 — moved, memory has tick 1 now
        g2 = build_creature_graph(agent, llm).compile()
        s2 = {**base_state, "raw_payload": _scenario_payload(creature_pos=(5, 0, 5))}
        f2 = await g2.ainvoke(s2)
        action2 = (f2.get("chosen_action") or {}).get("action", "")
        assert action2 in _ALL_AGENTBRIDGE_ACTIONS, f"Tick 2 hallucination: {action2!r}"

        assert agent.memory.tick_count == 2
        await agent.disconnect()


# ═════════════════════════════════════════════════════════════════════════════
#  5. @pytest.mark.paid + @pytest.mark.live — Real LLM AND real Unity
#
#  Requires both:
#    - LLM credentials in .env
#    - Unity open in Play mode with AgentBridge attached
#
#  Run:
#      pytest -m "paid and live" backend/tests/integration/test_graph_think.py -v -s
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.paid
@pytest.mark.live
class TestPaidLLMAndLiveUnity:
    """
    Real LLM + real Unity AgentBridge.

    The test fetches actual game state, lets the real LLM reason about it,
    then sends the decision to the running game.  Unity must ACK with ok=true.
    """

    UNITY_URL = "http://localhost:8080"

    @pytest.fixture(autouse=True)
    async def require_unity(self):
        if not await _unity_is_live(self.UNITY_URL):
            pytest.skip("Unity AgentBridge not reachable — open the game first.")

    async def _run_full(self, extra_scenario_entities: list[dict] | None = None) -> dict:
        client = HttpUnityClient(base_url=self.UNITY_URL, timeout=5.0)
        eye    = SnapshotManager(relevance_radius=30.0, threat_radius=10.0)
        memory = MemoryManager(max_ticks=50)
        body   = ActionManager(client=client)
        agent  = CreatureAgent(eye=eye, memory=memory, body=body)

        connected = await agent.connect()
        assert connected, "Failed to connect to AgentBridge"

        raw = await client.get_state()
        payload = {
            "creature_snapshot": {
                "position":      {"x": raw.get("posX", 0), "y": raw.get("posY", 0), "z": raw.get("posZ", 0)},
                "rotation_y":    raw.get("rotY", 0),
                "active_state":  raw.get("activeState", "none"),
                "active_stance": raw.get("activeStance", "none"),
                "grounded":      raw.get("grounded", True),
                "speed":         raw.get("speed", 0),
                "sprint":        raw.get("sprint", False),
            },
            "environment_snapshot": {
                "time_of_day": 12.0,
                "weather":     "clear",
                "entities":    extra_scenario_entities or [],
            },
        }

        state: AgentGraphState = {
            "raw_payload":       payload,
            "perception":        None,
            "perception_error":  None,
            "memory_context":    None,
            "chosen_action":     None,
            "reasoning":         None,
            "action_result":     None,
            "messages":          [],
            "tick":              0,
            "available_actions": list(agent.body.available_actions),
        }
        compiled = build_creature_graph(agent, _real_llm()).compile()
        final    = await compiled.ainvoke(state)
        await agent.disconnect()
        return final

    @pytest.mark.asyncio
    async def test_real_llm_perceives_live_state_no_error(self):
        """
        Real snapshot → real LLM → perception_error must be None.
        The LLM must produce a syntactically valid decision for real game data.
        """
        final = await self._run_full()

        assert final.get("perception_error") is None, (
            f"Perception failed on live state: {final.get('perception_error')}"
        )
        assert final["perception"] is not None
        action = (final.get("chosen_action") or {}).get("action", "")
        assert action, "LLM returned no action for live state"
        assert action in _ALL_AGENTBRIDGE_ACTIONS | {"wait"}, (
            f"LLM hallucinated '{action}' from live game state. "
            f"Valid: {sorted(_ALL_AGENTBRIDGE_ACTIONS)}"
        )

    @pytest.mark.asyncio
    async def test_real_llm_walk_acknowledged_by_unity(self):
        """
        Full pipeline: real game state → real LLM thinks → action sent → Unity ACKs.
        If LLM picks 'wait' the test still passes (LLM is non-deterministic).
        If LLM picks anything else, Unity must return ok=true.
        """
        final = await self._run_full()

        result = final.get("action_result", {})
        action = result.get("action", "")

        if action == "wait":
            pytest.skip(f"LLM chose 'wait' this run — re-run to test a movement action.")

        assert result.get("success") is True, (
            f"Action '{action}' failed: {result.get('detail')}\n"
            f"Reasoning: {final.get('reasoning')}"
        )

    @pytest.mark.asyncio
    async def test_real_llm_reasoning_is_non_empty(self):
        """
        The LLM must produce non-empty reasoning — proves it actually ran
        (not a timeout / empty response).
        """
        final = await self._run_full()
        reasoning = final.get("reasoning", "")
        assert reasoning, (
            "LLM returned empty reasoning — check LLM_* env vars and API connectivity"
        )
