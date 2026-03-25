"""
Unit tests for the agent_thinking_task background worker.

All external calls (Redis, Supabase) are mocked.
asyncio.sleep is patched to skip the 3-second delay.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.agent_tasks import agent_thinking_task


FAKE_LOG_ID = "log-abc-123"
FAKE_USER_ID = "user-xyz-789"


class TestAgentThinkingTask:
    @patch("app.workers.agent_tasks.asyncio.sleep", new_callable=AsyncMock)
    async def test_sets_thinking_then_idle(self, mock_sleep, settings, mock_redis, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=[{"id": FAKE_LOG_ID}])

        await agent_thinking_task(
            log_id=FAKE_LOG_ID,
            user_id=FAKE_USER_ID,
            content="今天很開心",
            supabase=mock_supabase,
            redis=mock_redis,
            settings=settings,
        )

        # Redis should have been called: thinking → idle
        calls = mock_redis.set.call_args_list
        assert len(calls) == 2
        assert calls[0].args == (f"agent_status:{FAKE_USER_ID}", "thinking")
        assert calls[1].args == (f"agent_status:{FAKE_USER_ID}", "idle")

    @patch("app.workers.agent_tasks.asyncio.sleep", new_callable=AsyncMock)
    async def test_updates_reply_in_supabase(self, mock_sleep, settings, mock_redis, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=[{"id": FAKE_LOG_ID}])

        await agent_thinking_task(
            log_id=FAKE_LOG_ID,
            user_id=FAKE_USER_ID,
            content="測試回覆",
            supabase=mock_supabase,
            redis=mock_redis,
            settings=settings,
        )

        # Supabase should have received an update call
        mock_supabase.table.assert_called_with("micrologs")
        mock_supabase._builder.update.assert_called_once()

    @patch("app.workers.agent_tasks.asyncio.sleep", new_callable=AsyncMock)
    async def test_restores_idle_on_error(self, mock_sleep, settings, mock_redis, mock_supabase):
        """Even if the repo.update() fails, status must return to idle."""
        mock_supabase._builder.execute.side_effect = RuntimeError("DB down")

        await agent_thinking_task(
            log_id=FAKE_LOG_ID,
            user_id=FAKE_USER_ID,
            content="error case",
            supabase=mock_supabase,
            redis=mock_redis,
            settings=settings,
        )

        # Last Redis call must be idle (the finally block)
        last_call = mock_redis.set.call_args_list[-1]
        assert last_call.args[1] == "idle"
