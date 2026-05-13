"""
Unit tests for AgentService.

Uses shared fixtures from tests/conftest.py:
  settings, mock_redis, mock_supabase

Local fixtures override/extend those where the Redis-buffer architecture
or the ENABLE_MEMORY_PIPELINE toggle requires different behaviour.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import Settings
from app.services.agent_service import AgentService
from app.services.semantic_service import SemanticService


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _exec_bg_pipeline(bg_mock):
    """
    Execute every async background task registered via BackgroundTasks.add_task.

    Flush ticks schedule _run_flush_pipeline as a BackgroundTask and return
    immediately.  Tests that need to assert on pipeline side-effects (DB writes,
    Redis status changes, graph invocations) must call this helper after
    triggering the flush so the pipeline actually runs before any assertion.
    """
    for call in list(bg_mock.add_task.call_args_list):
        fn       = call.args[0]
        fn_args  = call.args[1:]
        if asyncio.iscoroutinefunction(fn):
            await fn(*fn_args)


FAKE_CREATURE_ID = "creature-abc-123"
FAKE_GRAPH_RESULT = {
    "tick": 2,
    "action_result": {"success": True, "action": "wait", "detail": "pause"},
    "reasoning": "coast is clear",
}


# ── Module-level fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def pipeline_settings():
    """Settings with ENABLE_MEMORY_PIPELINE=True so flush logic activates."""
    return Settings(
        supabase_url="http://fake-supabase",
        supabase_publishable_key="fake-anon-key",
        supabase_secret_key="fake-secret-key",
        openai_api_key="fake-openai-key",
        ENABLE_MEMORY_PIPELINE=True,
    )


@pytest.fixture
def stateful_redis():
    """
    AsyncMock Redis that maintains real in-memory LIST state.

    Implements rpush / llen / lrange / delete with correct Redis semantics so
    AgentService's buffer logic (push → count → pop → clear) works end-to-end
    without a real Redis server.
    """
    _store: dict[str, list[str]] = {}

    async def _rpush(key, *values):
        _store.setdefault(key, []).extend(values)
        return len(_store[key])

    async def _llen(key):
        return len(_store.get(key, []))

    async def _lrange(key, start, stop):
        lst  = _store.get(key, [])
        end  = None if stop == -1 else stop + 1
        return lst[start:end]

    async def _delete(*keys):
        for k in keys:
            _store.pop(k, None)
        return len(keys)

    mock = AsyncMock()
    mock.rpush  = AsyncMock(side_effect=_rpush)
    mock.llen   = AsyncMock(side_effect=_llen)
    mock.lrange = AsyncMock(side_effect=_lrange)
    mock.delete = AsyncMock(side_effect=_delete)
    mock.set    = AsyncMock()
    mock.get    = AsyncMock(return_value=None)
    return mock


@pytest.fixture(autouse=True)
def _no_real_embedding(monkeypatch):
    """
    Prevent any real OpenAI embedding calls during unit tests.

    EmbeddingService.embed_text is patched to return a tiny fake vector
    so _flush_buffer completes without network I/O.
    """
    from app.services.embedding_service import EmbeddingService
    monkeypatch.setattr(EmbeddingService, "embed_text", lambda self, text: [0.1] * 5)


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.memory.tick_count   = 2
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
def svc(pipeline_settings, stateful_redis, mock_supabase, mock_agent, mock_graph):
    """
    Full AgentService with aggregation_limit=1 so every single tick is a flush.

    Uses pipeline_settings (ENABLE_MEMORY_PIPELINE=True) and stateful_redis
    so the Redis-buffer path is exercised end-to-end.
    """
    return AgentService(
        redis=stateful_redis,
        settings=pipeline_settings,
        agent=mock_agent,
        graph=mock_graph,
        supabase=mock_supabase,
        aggregation_limit=1,
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
        """Redis returns bytes — service must decode, not return b'idle'."""
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


class TestRunTick:
    async def test_sets_thinking_then_idle(self, svc, stateful_redis):
        bg = MagicMock()
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID, payload=_nested_payload(), background_tasks=bg
        )
        await _exec_bg_pipeline(bg)
        statuses = [c.args[1] for c in stateful_redis.set.call_args_list]
        assert statuses[0] == "thinking"
        assert statuses[-1] == "idle"

    async def test_invokes_graph_with_correct_state(self, svc, mock_graph, mock_agent):
        bg = MagicMock()
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID, payload=_nested_payload(), background_tasks=bg
        )
        await _exec_bg_pipeline(bg)
        graph_input = mock_graph.ainvoke.call_args.args[0]
        assert graph_input["tick"]              == mock_agent.memory.tick_count
        assert graph_input["available_actions"] == mock_agent.body.available_actions

    async def test_returns_processing_on_flush(self, svc):
        """Flush ticks return 202 immediately; the pipeline runs in the background."""
        result = await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload=_nested_payload(),
            background_tasks=MagicMock(),
        )
        assert result["status"] == "processing"

    async def test_schedules_flush_pipeline_as_background_task(
        self, svc, mock_background_tasks
    ):
        """A flush tick schedules exactly ONE background task: _run_flush_pipeline."""
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload=_nested_payload(),
            background_tasks=mock_background_tasks,
        )
        assert mock_background_tasks.add_task.call_count == 1
        assert mock_background_tasks.add_task.call_args.args[0] is svc._run_flush_pipeline

    async def test_restores_idle_on_graph_failure(self, svc, mock_graph, stateful_redis):
        """Graph crash inside the background pipeline must still reset status to idle."""
        async def mock_fail(*args, **kwargs):
            raise RuntimeError("LLM exploded")
        mock_graph.ainvoke = mock_fail

        bg = MagicMock()
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID, payload=_nested_payload(), background_tasks=bg
        )
        await _exec_bg_pipeline(bg)

        last_status = stateful_redis.set.call_args_list[-1].args[1]
        assert last_status == "idle"

    async def test_graceful_without_graph(self, pipeline_settings, stateful_redis):
        """Service without graph/agent pushes to Redis and returns buffering — no crash."""
        svc = AgentService(
            redis=stateful_redis,
            settings=pipeline_settings,
            aggregation_limit=1,
        )
        result = await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload=_nested_payload(),
            background_tasks=MagicMock(),
        )
        # count(1) >= limit(1) but graph/agent absent → graceful buffering
        assert result["status"] == "buffering"

    async def test_passes_creature_id_in_graph_state(self, svc, mock_graph):
        """creature_id must be forwarded into the graph state so nodes can do DB recall."""
        bg = MagicMock()
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID, payload=_nested_payload(), background_tasks=bg
        )
        await _exec_bg_pipeline(bg)
        graph_input = mock_graph.ainvoke.call_args.args[0]
        assert graph_input["creature_id"] == FAKE_CREATURE_ID

    async def test_hydrates_from_db_when_memory_empty(
        self, pipeline_settings, stateful_redis, mock_graph, mock_supabase
    ):
        """Cold start (tick_count == 0) with supabase available → hydrate_agent called."""
        empty_agent = MagicMock()
        empty_agent.memory.tick_count       = 0
        empty_agent.body.available_actions  = ["wait"]
        svc = AgentService(
            redis=stateful_redis,
            settings=pipeline_settings,
            agent=empty_agent,
            graph=mock_graph,
            supabase=mock_supabase,
            aggregation_limit=1,
        )
        with patch(
            "app.services.agent_service.hydrate_agent", new_callable=AsyncMock
        ) as mock_hydrate:
            bg = MagicMock()
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID, payload=_nested_payload(), background_tasks=bg
            )
            await _exec_bg_pipeline(bg)
        mock_hydrate.assert_called_once_with(
            empty_agent, mock_supabase, stateful_redis, creature_id=FAKE_CREATURE_ID
        )

    async def test_skips_hydration_when_memory_populated(self, svc):
        """tick_count > 0 → no DB round-trip, no matter what."""
        with patch(
            "app.services.agent_service.hydrate_agent", new_callable=AsyncMock
        ) as mock_hydrate:
            bg = MagicMock()
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID, payload=_nested_payload(), background_tasks=bg
            )
            await _exec_bg_pipeline(bg)
        mock_hydrate.assert_not_called()

    async def test_skips_hydration_without_supabase(
        self, pipeline_settings, stateful_redis, mock_graph
    ):
        """No supabase configured → hydrate_agent must never be called."""
        empty_agent = MagicMock()
        empty_agent.memory.tick_count       = 0
        empty_agent.body.available_actions  = ["wait"]
        svc = AgentService(
            redis=stateful_redis,
            settings=pipeline_settings,
            agent=empty_agent,
            graph=mock_graph,
            supabase=None,
            aggregation_limit=1,
        )
        with patch(
            "app.services.agent_service.hydrate_agent", new_callable=AsyncMock
        ) as mock_hydrate:
            bg = MagicMock()
            await svc.run_tick(
                creature_id=FAKE_CREATURE_ID, payload=_nested_payload(), background_tasks=bg
            )
            await _exec_bg_pipeline(bg)
        mock_hydrate.assert_not_called()

    async def test_skips_persist_when_no_supabase(
        self, pipeline_settings, stateful_redis, mock_agent, mock_graph, mock_background_tasks
    ):
        """Background pipeline completes and is scheduled even when Supabase is None."""
        svc = AgentService(
            redis=stateful_redis,
            settings=pipeline_settings,
            agent=mock_agent,
            graph=mock_graph,
            supabase=None,
            aggregation_limit=1,
        )
        await svc.run_tick(
            creature_id=FAKE_CREATURE_ID,
            payload=_nested_payload(0),
            background_tasks=mock_background_tasks,
        )
        # Pipeline IS scheduled — supabase=None doesn't prevent scheduling
        mock_background_tasks.add_task.assert_called_once()
        assert mock_background_tasks.add_task.call_args.args[0] is svc._run_flush_pipeline


# ── Buffer Aggregation ────────────────────────────────────────────────────────

@pytest.fixture
def per_table_supabase():
    """
    Supabase mock that routes to a dedicated builder per table.
    Lets tests assert on perception_snapshots inserts without false positives
    from creature_states / creatures inserts.
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
    other_builder      = _make_builder([])   # creature_states → empty → auto-registers

    client = MagicMock()
    client.table.side_effect = (
        lambda name: perception_builder if name == "perception_snapshots" else other_builder
    )
    client._perception = perception_builder
    client._other      = other_builder
    return client


@pytest.fixture
def svc_agg(pipeline_settings, stateful_redis, per_table_supabase, mock_agent, mock_graph):
    """AgentService with aggregation_limit=3 for fast buffer-flush testing."""
    return AgentService(
        redis=stateful_redis,
        settings=pipeline_settings,
        agent=mock_agent,
        graph=mock_graph,
        supabase=per_table_supabase,
        semantic_service=SemanticService(),
        aggregation_limit=3,
    )


class TestBufferAggregation:
    """Verify the X-to-1 snapshot compression pipeline (Redis-buffer edition)."""

    # Well-formed UUID → _to_db_id() returns it unchanged for direct DB assertions.
    CREATURE = "d3e4f5a6-b7c8-4d9e-af10-b1c2d3e4f5a6"

    async def test_buffer_grows_without_flush(
        self, svc_agg, per_table_supabase, stateful_redis
    ):
        """2 ticks with limit=3 → Redis LIST has 2 items, no DB insert yet."""
        for i in range(2):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), MagicMock())

        key = f"cat:buffer:{self.CREATURE}"
        assert await stateful_redis.llen(key) == 2
        per_table_supabase._perception.insert.assert_not_called()

    async def test_buffer_clears_after_flush(self, svc_agg, stateful_redis):
        """After limit is reached the Redis LIST is deleted (buffer is empty)."""
        for i in range(3):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), MagicMock())

        key = f"cat:buffer:{self.CREATURE}"
        assert await stateful_redis.llen(key) == 0

    async def test_last_snapshot_id_recorded_after_flush(self, svc_agg):
        """_state.last_snapshot_ids must be set to the UUID returned by Supabase."""
        bg = MagicMock()
        for i in range(3):
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), bg)
        await _exec_bg_pipeline(bg)

        assert svc_agg._state.last_snapshot_ids[self.CREATURE] == "snap-uuid-1"

    async def test_flush_inserts_correct_row_structure(self, svc_agg, per_table_supabase):
        """Flushed row must carry creature_id, summary_text, raw_payloads, request_id, pos_*."""
        payloads = [_nested_payload(i) for i in range(3)]
        bg = MagicMock()
        for p in payloads:
            await svc_agg.run_full_tick_flow(self.CREATURE, p, bg)
        await _exec_bg_pipeline(bg)

        row = per_table_supabase._perception.insert.call_args.args[0]

        assert row["creature_id"]  == self.CREATURE
        assert row["request_id"]   == payloads[-1]["requestId"]
        assert isinstance(row["summary_text"], str) and len(row["summary_text"]) > 0
        assert isinstance(row["raw_payloads"], list) and len(row["raw_payloads"]) == 3
        assert row["pos_x"] == float(2)   # payload index 2 → x=2.0
        assert row["pos_y"] == 0.0
        assert row["pos_z"] == 0.0

    async def test_fifo_called_on_flush(self, svc_agg):
        """_enforce_fifo_limit must be called once when the pipeline runs."""
        bg = MagicMock()
        with patch.object(svc_agg, "_enforce_fifo_limit") as mock_fifo:
            for i in range(3):
                await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), bg)
            await _exec_bg_pipeline(bg)
        mock_fifo.assert_called_once_with(self.CREATURE)

    async def test_second_flush_after_next_window(
        self, svc_agg, per_table_supabase, stateful_redis
    ):
        """After a flush, the next 3 ticks trigger a second flush (insert count = 2)."""
        for i in range(6):
            bg = MagicMock()
            await svc_agg.run_full_tick_flow(self.CREATURE, _nested_payload(i), bg)
            await _exec_bg_pipeline(bg)

        assert per_table_supabase._perception.insert.call_count == 2
        key = f"cat:buffer:{self.CREATURE}"
        assert await stateful_redis.llen(key) == 0

    async def test_independent_buffers_per_creature(self, svc_agg, stateful_redis):
        """Two creatures accumulate independently in separate Redis LIST keys."""
        creature_a = "creature-A"
        creature_b = "creature-B"

        for i in range(2):
            await svc_agg.run_full_tick_flow(creature_a, _nested_payload(i), MagicMock())
        await svc_agg.run_full_tick_flow(creature_b, _nested_payload(0), MagicMock())

        key_a = f"cat:buffer:{creature_a}"
        key_b = f"cat:buffer:{creature_b}"
        assert await stateful_redis.llen(key_a) == 2
        assert await stateful_redis.llen(key_b) == 1

    async def test_no_db_writes_when_supabase_none(
        self, pipeline_settings, stateful_redis, mock_agent, mock_graph
    ):
        """Service without Supabase buffers and flushes normally but skips all DB writes."""
        svc = AgentService(
            redis=stateful_redis,
            settings=pipeline_settings,
            agent=mock_agent,
            graph=mock_graph,
            supabase=None,
            aggregation_limit=3,
        )
        bg = MagicMock()
        for i in range(3):
            await svc.run_full_tick_flow(self.CREATURE, _nested_payload(i), bg)
        await _exec_bg_pipeline(bg)

        # Redis buffer was cleared after the flush
        key = f"cat:buffer:{self.CREATURE}"
        assert await stateful_redis.llen(key) == 0
        # _run_flush_pipeline was scheduled exactly once (on the 3rd / flush tick)
        assert bg.add_task.call_count == 1
        assert bg.add_task.call_args.args[0] is svc._run_flush_pipeline
