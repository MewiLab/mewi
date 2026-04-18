"""
Unit tests for the run_agent_job background worker.

Redis and the LangGraph are mocked — no real connections or LLM calls.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workers.agent_worker import run_agent_job


FAKE_JOB_ID = "abc12345"
FAKE_PAYLOAD = {"self": {"x": 0, "y": 0, "z": 0}, "mood": {"fear": 0.1}}


def make_fake_agent():
    agent = MagicMock()
    agent.memory.tick_count = 5
    agent.body.available_actions = ["wander", "sit", "follow"]
    return agent


def make_fake_graph(action="wander", kwargs=None):
    graph = AsyncMock()
    graph.ainvoke.return_value = {
        "action_result": {"action": action, "kwargs": kwargs or {}},
        "reasoning": "felt like wandering",
    }
    return graph


class TestRunAgentJobSuccess:
    async def test_invokes_graph_with_correct_state(self, settings, mock_redis):
        agent = make_fake_agent()
        graph = make_fake_graph()

        await run_agent_job(
            job_id=FAKE_JOB_ID,
            payload=FAKE_PAYLOAD,
            redis=mock_redis,
            settings=settings,
            graph=graph,
            agent=agent,
        )

        call_kwargs = graph.ainvoke.call_args[0][0]
        assert call_kwargs["raw_payload"] == FAKE_PAYLOAD
        assert call_kwargs["tick"] == 5
        assert call_kwargs["available_actions"] == ["wander", "sit", "follow"]

    async def test_writes_done_status_to_redis(self, settings, mock_redis):
        await run_agent_job(
            job_id=FAKE_JOB_ID,
            payload=FAKE_PAYLOAD,
            redis=mock_redis,
            settings=settings,
            graph=make_fake_graph("wander"),
            agent=make_fake_agent(),
        )

        mock_redis.set.assert_called_once()
        key, raw = mock_redis.set.call_args[0]
        assert key == f"job:{FAKE_JOB_ID}"
        stored = json.loads(raw)
        assert stored["status"] == "done"
        assert stored["action"] == "wander"

    async def test_stores_go_to_kwargs_flat(self, settings, mock_redis):
        graph = make_fake_graph("go_to", {"x": 10.0, "y": 0.0, "z": 5.0})

        await run_agent_job(
            job_id=FAKE_JOB_ID,
            payload=FAKE_PAYLOAD,
            redis=mock_redis,
            settings=settings,
            graph=graph,
            agent=make_fake_agent(),
        )

        _, raw = mock_redis.set.call_args[0]
        stored = json.loads(raw)
        assert stored["action"] == "go_to"
        assert stored["x"] == 10.0
        assert stored["z"] == 5.0

    async def test_stores_follow_target(self, settings, mock_redis):
        graph = make_fake_graph("follow", {"target": "Player"})

        await run_agent_job(
            job_id=FAKE_JOB_ID,
            payload=FAKE_PAYLOAD,
            redis=mock_redis,
            settings=settings,
            graph=graph,
            agent=make_fake_agent(),
        )

        _, raw = mock_redis.set.call_args[0]
        stored = json.loads(raw)
        assert stored["action"] == "follow"
        assert stored["target"] == "Player"


class TestRunAgentJobFailure:
    async def test_writes_error_status_on_graph_exception(self, settings, mock_redis):
        graph = AsyncMock()
        graph.ainvoke.side_effect = RuntimeError("LLM timeout")

        await run_agent_job(
            job_id=FAKE_JOB_ID,
            payload=FAKE_PAYLOAD,
            redis=mock_redis,
            settings=settings,
            graph=graph,
            agent=make_fake_agent(),
        )

        mock_redis.set.assert_called_once()
        key, raw = mock_redis.set.call_args[0]
        assert key == f"job:{FAKE_JOB_ID}"
        stored = json.loads(raw)
        assert stored["status"] == "error"

    async def test_does_not_raise_on_exception(self, settings, mock_redis):
        graph = AsyncMock()
        graph.ainvoke.side_effect = ValueError("bad payload")

        # Must not propagate — FastAPI BackgroundTask would swallow it anyway,
        # but the explicit catch ensures we always write an error key.
        await run_agent_job(
            job_id=FAKE_JOB_ID,
            payload=FAKE_PAYLOAD,
            redis=mock_redis,
            settings=settings,
            graph=graph,
            agent=make_fake_agent(),
        )
