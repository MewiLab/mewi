import logging

import redis.asyncio as aioredis
from supabase import Client

from app.core.config import Settings
from app.workers.base import BaseWorker
from app.services.microlog_service import MicrologService
from app.repositories.microlog_repo import MicrologRepository

logger = logging.getLogger(__name__)


class MicrologWorker(BaseWorker):
    """
    Periodically processes micrologs that are missing embeddings.
    MicrologWorker
    └── MicrologService            ← business logic: "process a microlog"
            ├── EmbeddingService   ← knows HOW to embed
            └── MicrologRepository ← knows HOW to persist
    """
    name = "microlog_worker"

    def __init__(self, *, supabase: Client, settings: Settings):
        super().__init__(interval_seconds=settings.microlog_worker_interval)
        self._svc = MicrologService(settings=settings, supabase=supabase)

    async def _run_once(self) -> None:
        count = self._svc.process_unembedded(limit=50)
        if count:
            logger.info("Worker processed %d micrologs", count)