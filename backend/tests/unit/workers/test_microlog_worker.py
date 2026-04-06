"""
Unit tests for MicrologWorker.

Uses shared fixtures from tests/conftest.py:
  settings, mock_supabase
"""

import logging
from unittest.mock import AsyncMock, patch
import pytest

from app.workers.microlog_worker import MicrologWorker


@pytest.fixture
def worker(settings, mock_supabase):
    return MicrologWorker(supabase=mock_supabase, settings=settings)


class TestMicrologWorkerTick:
    async def test_calls_process_unembedded(self, worker):
        with patch.object(worker._svc, "process_unembedded", return_value=3) as mock_process:
            await worker._run_once()
        mock_process.assert_called_once_with(limit=50)

    async def test_no_log_when_nothing_to_process(self, worker, caplog):
        with patch.object(worker._svc, "process_unembedded", return_value=0):
            await worker._run_once()
        assert "processed" not in caplog.text

    async def test_logs_count_when_records_processed(self, worker, caplog):
        with patch.object(worker._svc, "process_unembedded", return_value=7):
            with caplog.at_level(logging.INFO, logger="app.workers.microlog_worker"):
                await worker._run_once()
        assert "7" in caplog.text

    async def test_service_error_propagates(self, worker):
        """BaseWorker catches this — worker should not permanently die."""
        with patch.object(worker._svc, "process_unembedded", side_effect=RuntimeError("DB down")):
            with pytest.raises(RuntimeError):
                await worker._run_once()


class TestMicrologWorkerLifecycle:
    async def test_interval_comes_from_settings(self, settings, mock_supabase):
        settings.microlog_worker_interval = 45.0
        worker = MicrologWorker(supabase=mock_supabase, settings=settings)
        assert worker._interval == 45.0

    async def test_stop_sets_running_false(self, worker):
        await worker.stop()
        assert worker._running is False