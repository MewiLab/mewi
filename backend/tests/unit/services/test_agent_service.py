"""
Unit tests for AgentService.

Uses shared fixtures from tests/conftest.py:
  settings, mock_redis, mock_supabase
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.agent_service import AgentService
from app.services.semantic_service import SemanticService


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
        #    1. _save_behavior_decision  (DB write for the AI decision)
        #    2. persist_tick              (serialise tick to agent_tick_history)
        assert mock_background_tasks.add_task.call_count == 2
        mock_background_tasks.add_task.assert_any_call(
            mock_persist, svc._agent, mock_supabase, mock_redis, FAKE_CREATURE_ID
        )

    async def test_restores_idle_on_graph_failure(self, svc, mock_graph, mock_redis):
        """
        NEW BEHAVIOR: Graph crash must be caught and return a fallback result.
        The creature status must still be reset to 'idle'.
        """
        # [MODIFIED] Using an async side_effect to simulate a real AI timeout/failure
        async def mock_fail(*args, **kwargs):
            raise RuntimeError("LLM exploded")
        
        mock_graph.ainvoke = mock_fail

        # [MODIFIED] No longer using pytest.raises because AgentService now catches the error
        result = await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload={},
            background_tasks=MagicMock(),
        )

        # [NEW] Verify that we received the fallback 'wait' action instead of a crash
        assert result["action_result"]["action"] == "wait"
        assert result["action_result"]["metadata"]["reason"] == "AI_SERVICE_UNAVAILABLE"

        # [MODIFIED] Ensure status was still reset to idle at the end of the 'finally' block
        # We look at the very last call to redis.set
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


# ── Buffer Aggregation ────────────────────────────────────────────────────────

def _nested_payload(i: int = 0) -> dict:
    """Build a valid Unity nested-schema payload for AgentService tests."""
    return {
        "requestId": f"req-{i:03d}",
        "self": {
            "location":       {"x": float(i), "y": 0.0, "z": 0.0},
            "current_action": "walking",
        },
        "mood":   {"fear": 0.1, "trust": 0.8, "curiosity": 0.6, "social": 0.3, "energy": 0.9},
        "health": {"hunger": 0.2},
        "entities": [
            {"id": "lamp-1", "tags": ["lantern"], "distance": 3.0, "direction": "north"}
        ],
    }


@pytest.fixture
def per_table_supabase():
    """
    Supabase mock that routes to a dedicated builder per table.
    This lets tests assert on perception_snapshots inserts without
    false positives from creature_states / creatures inserts.
    """
    def _make_builder(return_data):
        b = MagicMock()
        b.insert.return_value  = b
        b.upsert.return_value  = b
        b.update.return_value  = b
        b.select.return_value  = b
        b.delete.return_value  = b
        b.eq.return_value      = b
        b.in_.return_value     = b
        b.order.return_value   = b
        b.limit.return_value   = b
        b.execute.return_value = MagicMock(data=return_data)
        return b

    perception_builder = _make_builder([{"id": "snap-uuid-1"}])
    other_builder      = _make_builder([])  # creature_states check returns empty → auto-registers

    client = MagicMock()
    client.table.side_effect = (
        lambda name: perception_builder if name == "perception_snapshots" else other_builder
    )
    client._perception = perception_builder
    client._other      = other_builder
    return client


@pytest.fixture
def svc_agg(settings, mock_redis, per_table_supabase, mock_agent, mock_graph):
    """AgentService with aggregation_limit=3 for fast buffer-flush testing."""
    return AgentService(
        redis=mock_redis,
        settings=settings,
        agent=mock_agent,
        graph=mock_graph,
        supabase=per_table_supabase,
        semantic_service=SemanticService(),
        aggregation_limit=3,
    )


class TestBufferAggregation:
    """Verify the X-to-1 snapshot compression pipeline."""

    CREATURE = "creature-buffer-001"

    async def test_buffer_grows_without_flush(self, svc_agg, per_table_supabase):
        """2 ticks with limit=3 → buffer grows, no perception_snapshots insert yet."""
        for i in range(2):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), MagicMock())

        assert len(svc_agg.buffers[self.CREATURE]) == 2
        per_table_supabase._perception.insert.assert_not_called()

    async def test_buffer_clears_after_flush(self, svc_agg):
        """After limit is reached, buffer for that creature is reset to empty."""
        for i in range(3):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), MagicMock())

        assert svc_agg.buffers.get(self.CREATURE, []) == []

    async def test_last_snapshot_id_recorded_after_flush(self, svc_agg):
        """_last_snapshot_ids must be set to the UUID returned by Supabase."""
        for i in range(3):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), MagicMock())

        assert svc_agg._last_snapshot_ids[self.CREATURE] == "snap-uuid-1"

    async def test_flush_inserts_correct_row_structure(self, svc_agg, per_table_supabase):
        """The flushed row must carry creature_id, summary_text, raw_payloads, and request_id."""
        payloads = [_nested_payload(i) for i in range(3)]
        for p in payloads:
            await svc_agg.run_full_tick_flow(self.CREATURE, p, MagicMock())

        row = per_table_supabase._perception.insert.call_args.args[0]

        assert row["creature_id"]  == self.CREATURE
        assert row["request_id"]   == payloads[-1]["requestId"]  # from the last snapshot
        assert isinstance(row["summary_text"], str) and len(row["summary_text"]) > 0
        assert isinstance(row["raw_payloads"], list) and len(row["raw_payloads"]) == 3
        # Position extracted from last snapshot's self.location
        assert row["pos_x"] == float(2)   # payload index 2 → x=2.0
        assert row["pos_y"] == 0.0
        assert row["pos_z"] == 0.0

    async def test_fifo_scheduled_as_background_task_on_flush(self, svc_agg):
        """_enforce_fifo_limit must be added as a BackgroundTask when the buffer flushes."""
        bg = MagicMock()
        for i in range(3):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), bg)

        fifo_calls = [
            c for c in bg.add_task.call_args_list
            if c.args[0] is svc_agg._enforce_fifo_limit
        ]
        assert len(fifo_calls) == 1
        # creature_id is the first positional arg after the function
        assert fifo_calls[0].args[1] == self.CREATURE

    async def test_second_flush_after_next_window(self, svc_agg, per_table_supabase):
        """After a flush, the next 3 ticks should trigger a second flush."""
        for i in range(6):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), MagicMock())

        assert per_table_supabase._perception.insert.call_count == 2
        assert svc_agg.buffers.get(self.CREATURE, []) == []

    async def test_independent_buffers_per_creature(self, svc_agg):
        """Two creatures accumulate independently — one full buffer must not affect the other."""
        creature_a, creature_b = "creature-A", "creature-B"

        for i in range(2):
            await svc_agg.run_full_tick_flow(creature_a, _nested_payload(i), MagicMock())
        await svc_agg.run_full_tick_flow(creature_b, _nested_payload(0), MagicMock())

        assert len(svc_agg.buffers[creature_a]) == 2
        assert len(svc_agg.buffers[creature_b]) == 1

    async def test_no_flush_and_no_fifo_when_supabase_none(self, settings, mock_redis, mock_agent, mock_graph):
        """Service without Supabase must buffer normally but never touch DB or schedule FIFO."""
        svc = AgentService(
            redis=mock_redis,
            settings=settings,
            agent=mock_agent,
            graph=mock_graph,
            supabase=None,
            aggregation_limit=3,
        )
        bg = MagicMock()
        for i in range(3):
            await svc.run_full_tick_flow(self.CREATURE, _nested_payload(i), bg)

        # Buffer flushed in memory but no DB write happened
        assert svc.buffers.get(self.CREATURE, []) == []
        # No FIFO task because _supabase is None (early return in _enforce_fifo_limit)
        # The bg.add_task calls that DID happen are for behavior_decisions and persist_tick
        # — but supabase is None so those are also skipped
        bg.add_task.assert_not_called()