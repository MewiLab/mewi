"""
test_perception_flow.py — Simulates the full Unity → Backend → Action pipeline.

Tests the Perception-to-Action loop without requiring a running LLM, Redis,
or Supabase.  The LLM is replaced with an AsyncMock that returns realistic
JSON responses, so every assertion is about pipeline correctness, not model
output.

Coverage:
  1. AgentService.snapshot_to_prompt()  — text conversion
  2. Full LangGraph tick                — perceive→remember→reason→act→reflect
  3. log_contextual_decision()          — contextual retrieval memory log
  4. run_agent_job()                    — end-to-end worker with mock deps
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.creature_agent import CreatureAgent
from app.agent.perception import SnapshotManager
from app.agent.memory import MemoryManager
from app.agent.action import ActionManager
from app.agent.graph import build_creature_graph
from app.agent.schemas.perception_schema import PerceptionSummary
from app.services.agent_service import AgentService
from app.services.memory_service import (
    log_contextual_decision,
    _build_context_header,
    _estimate_valence,
    _estimate_arousal,
)
from tests.mock_unity_client import MockUnityClient


# ─── Reusable payloads ───────────────────────────────────────────────────────

PREDATOR_PAYLOAD = {
    "creature_snapshot": {
        "position": {"x": 5.0, "y": 0.0, "z": 8.0},
        "rotation_y": 45.0,
        "active_state": "Locomotion",
        "active_stance": "Default",
        "grounded": True,
        "speed": 2.5,
        "sprint": False,
    },
    "environment_snapshot": {
        "time_of_day": 18.5,
        "weather": "cloudy",
        "entities": [
            {
                "name": "Wolf",
                "tag": "predator",
                "position": {"x": 7.0, "y": 0.0, "z": 10.0},
                "distance": 2.8,
            },
            {
                "name": "Pond",
                "tag": "water",
                "position": {"x": 20.0, "y": 0.0, "z": 5.0},
                "distance": 15.4,
            },
        ],
    },
}

CALM_PAYLOAD = {
    "creature_snapshot": {
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation_y": 0.0,
        "active_state": "Idle",
        "active_stance": "Default",
        "grounded": True,
        "speed": 0.0,
        "sprint": False,
    },
    "environment_snapshot": {
        "time_of_day": 10.0,
        "weather": "sunny",
        "entities": [],
    },
}


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def connected_agent():
    """CreatureAgent wired to a connected MockUnityClient."""
    client = MockUnityClient()
    client.add_action("Sprint", "toggle", "Hold to sprint")
    client.add_action("Jump", "press", "Jump or climb surface")
    client.add_action("Attack1", "press", "Primary attack")
    client._connected = True

    agent = CreatureAgent(
        eye=SnapshotManager(relevance_radius=30.0, threat_radius=10.0),
        memory=MemoryManager(max_ticks=20),
        body=ActionManager(client=client),
    )
    return agent, client


def _make_llm(action: str, kwargs: dict, reasoning: str) -> AsyncMock:
    """Build a mock LLM that returns a specific decision."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value=MagicMock(
        content=json.dumps({
            "action": action,
            "kwargs": kwargs,
            "reasoning": reasoning,
        })
    ))
    return mock


def _mock_supabase():
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.execute.return_value = MagicMock(data=[{"id": "fake-id"}])
    client = MagicMock()
    client.table.return_value = builder
    return client, builder


# ─── 1. snapshot_to_prompt ───────────────────────────────────────────────────

class TestSnapshotToPrompt:

    def test_returns_string(self):
        text = AgentService.snapshot_to_prompt(PREDATOR_PAYLOAD)
        assert isinstance(text, str)
        assert len(text) > 20

    def test_includes_threat_level(self):
        text = AgentService.snapshot_to_prompt(PREDATOR_PAYLOAD)
        # Wolf at 2.8 m is within 10 m threat radius → DANGER
        assert "DANGER" in text

    def test_includes_entity_names(self):
        text = AgentService.snapshot_to_prompt(PREDATOR_PAYLOAD)
        assert "Wolf" in text

    def test_includes_position(self):
        text = AgentService.snapshot_to_prompt(PREDATOR_PAYLOAD)
        assert "5.0" in text  # creature x position

    def test_calm_payload_shows_safe(self):
        text = AgentService.snapshot_to_prompt(CALM_PAYLOAD)
        assert "SAFE" in text
        assert "No entities" in text

    def test_invalid_payload_returns_error_string(self):
        bad = {"creature_snapshot": {"position": {"x": "not_a_number"}}}
        text = AgentService.snapshot_to_prompt(bad)
        assert isinstance(text, str)
        assert "error" in text.lower()


# ─── 2. Full LangGraph pipeline ───────────────────────────────────────────────

class TestPerceptionToActionPipeline:

    def _initial_state(self, agent, payload):
        return {
            "raw_payload":      payload,
            "messages":         [],
            "tick":             agent.memory.tick_count,
            "available_actions": agent.body.available_actions,
            "perception":       None,
            "perception_error": None,
            "memory_context":   None,
            "chosen_action":    None,
            "reasoning":        None,
            "action_result":    None,
            "goal":             None,
            "internal_state":   None,
        }

    @pytest.mark.asyncio
    async def test_predator_produces_valid_action(self, connected_agent):
        agent, _ = connected_agent
        llm = _make_llm("move", {"x": -1.0, "y": -1.0, "hold": 0.5},
                        "Wolf at 2.8m — fleeing diagonally.")
        graph = build_creature_graph(agent, llm).compile()

        state = await graph.ainvoke(self._initial_state(agent, PREDATOR_PAYLOAD))

        action_result = state.get("action_result")
        assert action_result is not None
        assert action_result["action"] == "move"
        assert isinstance(action_result["kwargs"], dict)

    @pytest.mark.asyncio
    async def test_perception_captures_danger_threat(self, connected_agent):
        agent, _ = connected_agent
        llm = _make_llm("move", {"x": 0.0, "y": -1.0, "hold": 0.4}, "Fleeing.")
        graph = build_creature_graph(agent, llm).compile()

        state = await graph.ainvoke(self._initial_state(agent, PREDATOR_PAYLOAD))

        perception = state.get("perception")
        assert perception is not None
        assert perception["threat_level"] == "danger"
        assert state.get("perception_error") is None

    @pytest.mark.asyncio
    async def test_reasoning_string_populated(self, connected_agent):
        agent, _ = connected_agent
        llm = _make_llm("Sprint", {"hold": 0.3}, "Sprinting away from threat.")
        graph = build_creature_graph(agent, llm).compile()

        state = await graph.ainvoke(self._initial_state(agent, PREDATOR_PAYLOAD))

        assert state.get("reasoning")
        assert "threat" in state["reasoning"].lower()

    @pytest.mark.asyncio
    async def test_wait_action_is_valid_terminal_state(self, connected_agent):
        agent, _ = connected_agent
        llm = _make_llm("wait", {}, "Nothing requires action.")
        graph = build_creature_graph(agent, llm).compile()

        state = await graph.ainvoke(self._initial_state(agent, CALM_PAYLOAD))

        action_result = state.get("action_result")
        assert action_result is not None
        assert action_result["action"] == "wait"

    @pytest.mark.asyncio
    async def test_bad_payload_produces_wait_not_crash(self, connected_agent):
        """Malformed Unity snapshot → perception_error → act emits 'wait'."""
        agent, _ = connected_agent
        llm = _make_llm("wait", {}, "No data.")
        graph = build_creature_graph(agent, llm).compile()

        state = await graph.ainvoke({
            **self._initial_state(agent, {}),
            "raw_payload": {"creature_snapshot": {"position": {"x": "bad"}}},
        })

        # Graph must not raise; action should fall back to 'wait'
        action_result = state.get("action_result")
        assert action_result is not None
        assert action_result["action"] == "wait"

    @pytest.mark.asyncio
    async def test_memory_updated_after_tick(self, connected_agent):
        agent, _ = connected_agent
        initial = agent.memory.tick_count
        llm = _make_llm("move", {"x": 0.0, "y": 1.0, "hold": 0.3}, "Exploring.")
        graph = build_creature_graph(agent, llm).compile()

        await graph.ainvoke(self._initial_state(agent, PREDATOR_PAYLOAD))

        assert agent.memory.tick_count == initial + 1

    @pytest.mark.asyncio
    async def test_llm_markdown_json_parsed_correctly(self, connected_agent):
        """LLM wrapping JSON in ```json ... ``` fences must not fall back to wait."""
        agent, _ = connected_agent
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='```json\n{"action":"Jump","kwargs":{"hold":0.2},"reasoning":"Testing."}\n```'
        ))
        graph = build_creature_graph(agent, mock_llm).compile()

        state = await graph.ainvoke(self._initial_state(agent, CALM_PAYLOAD))

        assert state["action_result"]["action"] == "Jump"

    @pytest.mark.asyncio
    async def test_goal_and_internal_state_flow_to_reason(self, connected_agent):
        """goal and internal_state fields should reach the reason node without error."""
        agent, _ = connected_agent
        llm = _make_llm("move", {"x": 0.0, "y": 1.0, "hold": 0.3}, "Following goal.")
        graph = build_creature_graph(agent, llm).compile()

        state = await graph.ainvoke({
            **self._initial_state(agent, CALM_PAYLOAD),
            "goal": "Find the food bowl.",
            "internal_state": {"energy": 0.4, "hunger": 0.8, "mood": "anxious"},
        })

        assert state.get("action_result") is not None


# ─── 3. Contextual memory logging ────────────────────────────────────────────

class TestContextualMemoryLog:

    @pytest.mark.asyncio
    async def test_writes_to_micrologs_table(self):
        supabase, builder = _mock_supabase()

        await log_contextual_decision(
            action="move",
            reasoning="Fleeing Wolf at 2.8 m.",
            perception_ctx={
                "tick": 7,
                "threat_level": "danger",
                "creature": {"position": {"x": 5.0, "y": 0.0, "z": 8.0}},
                "environment": {"weather": "cloudy", "time_of_day": 18.5},
                "entity_count": 2,
            },
            supabase=supabase,
        )

        supabase.table.assert_called_once_with("micrologs")
        builder.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_content_contains_context_and_decision(self):
        supabase, builder = _mock_supabase()

        await log_contextual_decision(
            action="Sprint",
            reasoning="Sprinting away.",
            perception_ctx={
                "tick": 12,
                "threat_level": "danger",
                "creature": {"position": {"x": 0.0, "y": 0.0, "z": 0.0}},
                "environment": {"weather": "sunny"},
                "entity_count": 1,
            },
            supabase=supabase,
        )

        insert_data = builder.insert.call_args[0][0]
        assert "tick=12" in insert_data["content"]
        assert "DANGER" in insert_data["content"]
        assert "Sprint" in insert_data["content"]
        assert "Sprinting away." in insert_data["content"]

    @pytest.mark.asyncio
    async def test_never_raises_on_supabase_error(self):
        """A DB failure must never propagate — agent pipeline must not be blocked."""
        supabase = MagicMock()
        supabase.table.side_effect = Exception("Connection refused")

        # Must not raise
        await log_contextual_decision(
            action="wait",
            reasoning="Calm.",
            perception_ctx={},
            supabase=supabase,
        )

    def test_context_header_format(self):
        ctx = {
            "tick": 3,
            "threat_level": "caution",
            "creature": {"position": {"x": 10.0, "y": 0.0, "z": 5.0}},
            "environment": {"weather": "rain"},
            "entity_count": 1,
        }
        header = _build_context_header(ctx)
        assert "tick=3" in header
        assert "CAUTION" in header
        assert "10.0" in header
        assert "rain" in header

    def test_empty_context_header_is_safe(self):
        header = _build_context_header({})
        assert isinstance(header, str)
        assert len(header) > 0

    def test_valence_negative_for_danger(self):
        assert _estimate_valence("move", {"threat_level": "danger"}) < 0

    def test_valence_positive_for_jump(self):
        assert _estimate_valence("Jump", {"threat_level": "safe"}) > 0

    def test_arousal_high_for_danger(self):
        assert _estimate_arousal("move", {"threat_level": "danger"}) >= 0.5

    def test_arousal_low_for_wait(self):
        assert _estimate_arousal("wait", {"threat_level": "safe"}) < 0.3


# ─── 4. Worker end-to-end ────────────────────────────────────────────────────

class TestRunAgentJob:

    @pytest.mark.asyncio
    async def test_job_completes_with_valid_action(self, connected_agent, mock_settings):
        from app.workers.agent_worker import run_agent_job

        agent, _ = connected_agent
        llm = _make_llm("move", {"x": -1.0, "y": -1.0, "hold": 0.5}, "Fleeing.")
        graph = build_creature_graph(agent, llm).compile()

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        supabase, _ = _mock_supabase()

        await run_agent_job(
            job_id="testjob01",
            payload=PREDATOR_PAYLOAD,
            redis=mock_redis,
            settings=mock_settings,
            graph=graph,
            agent=agent,
            supabase=supabase,
        )

        # Redis must have been called with a "done" result
        assert mock_redis.set.called
        set_key, set_value = mock_redis.set.call_args[0][:2]
        stored = json.loads(set_value)
        assert stored["status"] == "done"
        assert stored.get("action") in agent.body.available_actions + ["wait"]

    @pytest.mark.asyncio
    async def test_job_fails_gracefully_on_graph_error(self, connected_agent, mock_settings):
        """If the graph itself raises, the worker writes {"status":"error"} to Redis."""
        from app.workers.agent_worker import run_agent_job

        agent, _ = connected_agent

        broken_graph = AsyncMock()
        broken_graph.ainvoke = AsyncMock(side_effect=RuntimeError("Graph exploded"))

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        await run_agent_job(
            job_id="testjob02",
            payload=PREDATOR_PAYLOAD,
            redis=mock_redis,
            settings=mock_settings,
            graph=broken_graph,
            agent=agent,
        )

        assert mock_redis.set.called
        set_key, set_value = mock_redis.set.call_args[0][:2]
        stored = json.loads(set_value)
        assert stored["status"] == "error"

    @pytest.mark.asyncio
    async def test_job_works_without_supabase(self, connected_agent, mock_settings):
        """supabase=None is valid — memory logging is skipped silently."""
        from app.workers.agent_worker import run_agent_job

        agent, _ = connected_agent
        llm = _make_llm("wait", {}, "Nothing to do.")
        graph = build_creature_graph(agent, llm).compile()

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        await run_agent_job(
            job_id="testjob03",
            payload=CALM_PAYLOAD,
            redis=mock_redis,
            settings=mock_settings,
            graph=graph,
            agent=agent,
            supabase=None,  # explicit: no DB
        )

        assert mock_redis.set.called
