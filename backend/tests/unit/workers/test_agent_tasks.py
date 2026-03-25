"""
Unit tests for the agent_thinking_task background worker.

All external calls (Redis, Supabase) are mocked.
asyncio.sleep is patched to skip the 3-second delay.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.agent_tasks import agent_thinking_task


FAKE_CREATURE_ID = "creature-abc-123"
FAKE_SNAPSHOT = {"location": "park", "mood": "curious", "nearby_humans": 2}


class TestAgentThinkingTask:
    @patch("app.workers.agent_tasks.asyncio.sleep", new_callable=AsyncMock)
    async def test_sets_thinking_then_idle(self, mock_sleep, settings, mock_redis, mock_supabase):
        await agent_thinking_task(
            creature_id=FAKE_CREATURE_ID,
            snapshot=FAKE_SNAPSHOT,
            supabase=mock_supabase,
            redis=mock_redis,
            settings=settings,
        )

        # Redis should have been called: thinking → idle
        calls = mock_redis.set.call_args_list
        assert len(calls) == 2
        assert calls[0].args == (f"agent_status:{FAKE_CREATURE_ID}", "thinking")
        assert calls[1].args == (f"agent_status:{FAKE_CREATURE_ID}", "idle")

    @patch("app.workers.agent_tasks.asyncio.sleep", new_callable=AsyncMock)
    async def test_sleep_simulates_thinking(self, mock_sleep, settings, mock_redis, mock_supabase):
        await agent_thinking_task(
            creature_id=FAKE_CREATURE_ID,
            snapshot=FAKE_SNAPSHOT,
            supabase=mock_supabase,
            redis=mock_redis,
            settings=settings,
        )

        mock_sleep.assert_awaited_once()

    @patch("app.workers.agent_tasks.asyncio.sleep", new_callable=AsyncMock)
    async def test_restores_idle_on_error(self, mock_sleep, settings, mock_redis, mock_supabase):
        """Even if thinking raises, status must return to idle."""
        mock_sleep.side_effect = RuntimeError("thinking exploded")

        await agent_thinking_task(
            creature_id=FAKE_CREATURE_ID,
            snapshot=FAKE_SNAPSHOT,
            supabase=mock_supabase,
            redis=mock_redis,
            settings=settings,
        )

        # Last Redis call must be idle (the finally block)
        last_call = mock_redis.set.call_args_list[-1]
        assert last_call.args[1] == "idle"
