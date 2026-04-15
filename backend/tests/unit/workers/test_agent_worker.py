"""
Unit tests for AgentWorker.

Uses shared fixtures from tests/conftest.py:
  settings, mock_redis, mock_supabase
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.workers.agent_worker import AgentWorker


FAKE_CREATURE_ID = "creature-abc-123"
FAKE_GRAPH_RESULT = {
    "tick": 1,
    "action_result": {"success": True, "action": "wait", "detail": "pause"},
    "reasoning": "nothing nearby",
}


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.memory.tick_count = 1
    agent.body.available_actions = ["wait", "move", "stop"]
    agent.body.get_state = AsyncMock(return_value={})
    return agent


@pytest.fixture
def mock_graph():
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=FAKE_GRAPH_RESULT)
    return graph


@pytest.fixture
def worker(settings, mock_redis, mock_supabase, mock_agent, mock_graph):
    return AgentWorker(
        creature_id=FAKE_CREATURE_ID,
        agent=mock_agent,
        graph=mock_graph,
        redis=mock_redis,
        supabase=mock_supabase,
        settings=settings,
        interval_seconds=10.0,
    )


class TestAgentWorkerTick:
    async def test_sets_thinking_then_idle(self, worker, mock_redis):
        await worker._run_once()

        statuses = [c.args[1] for c in mock_redis.set.call_args_list]
        assert statuses[0] == "thinking"
        assert statuses[-1] == "idle"

    async def test_invokes_graph_with_agent_state(self, worker, mock_graph, mock_agent):
        await worker._run_once()

        payload = mock_graph.ainvoke.call_args.args[0]
        assert payload["tick"] == mock_agent.memory.tick_count
        assert payload["available_actions"] == mock_agent.body.available_actions

    async def test_restores_idle_on_graph_failure(self, worker, mock_graph, mock_redis):
        """Graph crash must never leave creature stuck in 'thinking'."""
        mock_graph.ainvoke.side_effect = RuntimeError("LLM timeout")

        with pytest.raises(RuntimeError):
            await worker._run_once()

        last_status = mock_redis.set.call_args_list[-1].args[1]
        assert last_status == "idle"

    async def test_calls_persist_tick_after_success(self, worker, mock_supabase, mock_redis):
        with patch("app.workers.agent_worker.persist_tick", new_callable=AsyncMock) as mock_persist:
            await worker._run_once()
        mock_persist.assert_awaited_once_with(worker._agent, mock_supabase, mock_redis)


class TestAgentWorkerLifecycle:
    async def test_stop_sets_running_false(self, worker):
        await worker.stop()
        assert worker._running is False

    async def test_run_once_called_in_start_loop(self, worker):
        call_count = 0

        async def fake_run_once():
            nonlocal call_count
            call_count += 1
            await worker.stop()

        worker._run_once = fake_run_once

        with patch("app.workers.base.asyncio.sleep", new_callable=AsyncMock):
            await worker.start()

        assert call_count == 1