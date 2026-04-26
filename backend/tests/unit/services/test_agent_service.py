"""
Unit tests for AgentService.

Uses shared fixtures from tests/conftest.py:
  settings, mock_redis, mock_supabase
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.agent_service import AgentService


FAKE_CREATURE_ID = "creature-abc-123"
FAKE_GRAPH_RESULT = {
    "tick": 2,
    "action_result": {"success": True, "action": "wait", "detail": "pause"},
    "reasoning": "coast is clear",
}


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.memory.tick_count = 2
    agent.body.available_actions = ["wait", "move", "stop"]
    return agent


@pytest.fixture
def mock_graph():
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=FAKE_GRAPH_RESULT)
    return graph


@pytest.fixture
def mock_background_tasks():
    bt = MagicMock()
    bt.add_task = MagicMock()
    return bt


@pytest.fixture
def svc(settings, mock_redis, mock_supabase, mock_agent, mock_graph):
    return AgentService(
        redis=mock_redis,
        settings=settings,
        agent=mock_agent,
        graph=mock_graph,
        supabase=mock_supabase,
    )


@pytest.fixture
def status_only_svc(settings, mock_redis):
    """AgentService with no graph/agent — for status-only tests."""
    return AgentService(redis=mock_redis, settings=settings)


# ── Status ────────────────────────────────────────────────────────────────────

class TestGetStatus:
    async def test_returns_stored_value(self, status_only_svc, mock_redis):
        mock_redis.get.return_value = b"thinking"
        assert await status_only_svc.get_status(FAKE_CREATURE_ID) == "thinking"
        mock_redis.get.assert_called_once_with(f"agent_status:{FAKE_CREATURE_ID}")

    async def test_defaults_to_idle_when_missing(self, status_only_svc, mock_redis):
        mock_redis.get.return_value = None
        assert await status_only_svc.get_status(FAKE_CREATURE_ID) == "idle"

    async def test_decodes_bytes_from_redis(self, status_only_svc, mock_redis):
        """Redis returns bytes — service must decode, not return b'thinking'."""
        mock_redis.get.return_value = b"idle"
        result = await status_only_svc.get_status(FAKE_CREATURE_ID)
        assert result == "idle"
        assert isinstance(result, str)


class TestSetStatus:
    async def test_writes_key_with_ttl(self, status_only_svc, mock_redis, settings):
        await status_only_svc._set_status(FAKE_CREATURE_ID, "thinking")
        mock_redis.set.assert_called_once_with(
            f"agent_status:{FAKE_CREATURE_ID}",
            "thinking",
            ex=settings.agent_status_ttl,
        )

    async def test_custom_ttl_from_settings(self, mock_redis):
        from app.core.config import Settings
        custom = Settings(
            supabase_url="http://fake",
            supabase_publishable_key="k",
            supabase_secret_key="k",
            openai_api_key="k",
            agent_status_ttl=999,
        )
        svc = AgentService(redis=mock_redis, settings=custom)
        await svc._set_status(FAKE_CREATURE_ID, "idle")
        mock_redis.set.assert_called_once_with(
            f"agent_status:{FAKE_CREATURE_ID}", "idle", ex=999
        )


# ── run_tick ──────────────────────────────────────────────────────────────────

class TestRunTick:
    async def test_sets_thinking_then_idle(self, svc, mock_redis):
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload={"raw": "data"},
            background_tasks=MagicMock(),
        )
        statuses = [c.args[1] for c in mock_redis.set.call_args_list]
        assert statuses[0] == "thinking"
        assert statuses[-1] == "idle"

    async def test_invokes_graph_with_correct_state(self, svc, mock_graph, mock_agent):
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload={"raw": "data"},
            background_tasks=MagicMock(),
        )
        payload = mock_graph.ainvoke.call_args.args[0]
        assert payload["tick"] == mock_agent.memory.tick_count
        assert payload["available_actions"] == mock_agent.body.available_actions

    async def test_returns_graph_result(self, svc):
        result = await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload={},
            background_tasks=MagicMock(),
        )
        assert result["tick"] == FAKE_GRAPH_RESULT["tick"]
        assert result["action_result"] == FAKE_GRAPH_RESULT["action_result"]

    async def test_schedules_persist_as_background_task(
        self, svc, mock_background_tasks, mock_supabase, mock_redis
    ):
        with patch("app.services.agent_service.persist_tick") as mock_persist:
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID,
                payload={},
                background_tasks=mock_background_tasks,
            )
        # run_full_tick_flow schedules 2 background tasks:
        #   1. _save_behavior_decision  (DB write for the AI decision)
        #   2. persist_tick             (serialise tick to agent_tick_history)
        assert mock_background_tasks.add_task.call_count == 2
        mock_background_tasks.add_task.assert_any_call(
            mock_persist, svc._agent, mock_supabase, mock_redis, FAKE_CREATURE_ID
        )

    async def test_restores_idle_on_graph_failure(self, svc, mock_graph, mock_redis):
        """Graph crash must never leave creature stuck in 'thinking'."""
        mock_graph.ainvoke.side_effect = RuntimeError("LLM exploded")

        with pytest.raises(RuntimeError):
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID,
                payload={},
                background_tasks=MagicMock(),
            )

        last_status = mock_redis.set.call_args_list[-1].args[1]
        assert last_status == "idle"

    async def test_raises_without_graph(self, settings, mock_redis):
        """Calling run_tick on a status-only service must fail clearly."""
        svc = AgentService(redis=mock_redis, settings=settings)
        with pytest.raises(RuntimeError, match="requires graph and agent"):
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID,
                payload={},
                background_tasks=MagicMock(),
            )

    async def test_passes_creature_id_in_graph_state(self, svc, mock_graph):
        """creature_id must be forwarded into the graph state so nodes can do DB recall."""
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload={},
            background_tasks=MagicMock(),
        )
        payload = mock_graph.ainvoke.call_args.args[0]
        assert payload["creature_id"] == FAKE_CREATURE_ID

    async def test_hydrates_from_db_when_memory_empty(
        self, settings, mock_redis, mock_graph, mock_supabase
    ):
        """Cold start (tick_count == 0) with supabase available → hydrate_agent called."""
        empty_agent = MagicMock()
        empty_agent.memory.tick_count = 0
        empty_agent.body.available_actions = ["wait"]
        svc = AgentService(
            redis=mock_redis,
            settings=settings,
            agent=empty_agent,
            graph=mock_graph,
            supabase=mock_supabase,
        )
        with patch(
            "app.services.agent_service.hydrate_agent", new_callable=AsyncMock
        ) as mock_hydrate:
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID,
                payload={},
                background_tasks=MagicMock(),
            )
        mock_hydrate.assert_called_once_with(
            empty_agent, mock_supabase, mock_redis, creature_id=FAKE_CREATURE_ID
        )

    async def test_skips_hydration_when_memory_populated(self, svc):
        """tick_count > 0 → no DB round-trip, no matter what."""
        with patch(
            "app.services.agent_service.hydrate_agent", new_callable=AsyncMock
        ) as mock_hydrate:
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID,
                payload={},
                background_tasks=MagicMock(),
            )
        mock_hydrate.assert_not_called()

    async def test_skips_hydration_without_supabase(
        self, settings, mock_redis, mock_graph
    ):
        """No supabase configured → hydrate_agent must never be called."""
        empty_agent = MagicMock()
        empty_agent.memory.tick_count = 0
        empty_agent.body.available_actions = ["wait"]
        svc = AgentService(
            redis=mock_redis,
            settings=settings,
            agent=empty_agent,
            graph=mock_graph,
            supabase=None,
        )
        with patch(
            "app.services.agent_service.hydrate_agent", new_callable=AsyncMock
        ) as mock_hydrate:
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID,
                payload={},
                background_tasks=MagicMock(),
            )
        mock_hydrate.assert_not_called()

    async def test_skips_persist_when_no_supabase(
        self, settings, mock_redis, mock_agent, mock_graph, mock_background_tasks
    ):
        """Service without supabase should still complete — just skip persist."""
        svc = AgentService(
            redis=mock_redis,
            settings=settings,
            agent=mock_agent,
            graph=mock_graph,
            supabase=None,
        )
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload={},
            background_tasks=mock_background_tasks,
        )
        mock_background_tasks.add_task.assert_not_called()