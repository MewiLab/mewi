"""
Base class for all background workers.

Every worker gets: start/stop lifecycle, error isolation,
configurable interval, and structured logging for free.
Adding a new worker = subclass + override _run_once().
"""
import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """
    Periodic async worker. Subclasses implement _run_once().

    Usage in lifespan.py:
        worker = MyWorker(interval_seconds=10)
        task = asyncio.create_task(worker.start())
        ...
        await worker.stop()
    """

    name: str = "unnamed_worker"

    def __init__(self, interval_seconds: float):
        self._interval = interval_seconds
        self._running  = False
        self._task: asyncio.Task | None = None
        self._log = logging.getLogger(f"app.workers.{self.name}")

    async def start(self) -> None:
        self._running = True
        self._log.info("Worker started (interval=%.1fs)", self._interval)
        while self._running:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                break
            except Exception:
                # Isolate failures — one bad tick never kills the worker
                self._log.exception("Worker tick failed, continuing")
            await asyncio.sleep(self._interval)
        self._log.info("Worker stopped")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    @abstractmethod
    async def _run_once(self) -> None:
        """Single unit of work. Called every interval_seconds."""
        ...