import logging
from app.core.config import Settings
from app.models.microlog import MicrologCreate, MicrologInDB, MicrologRead
from app.repositories.microlog_repo import MicrologRepository
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class MicrologService:
    def __init__(self, settings: Settings, supabase):
        self._embedder = EmbeddingService(settings)
        self._repo     = MicrologRepository(supabase)

    def create(self, body: MicrologCreate) -> MicrologRead:
        """Embed content and persist. Called by the router."""
        vector   = self._embedder.embed_text(body.content)
        enriched = MicrologInDB(**body.model_dump(), embedding=vector or None)
        return self._repo.create(enriched)

    def process_unembedded(self, limit: int = 50) -> int:
        """
        Embed any micrologs that are missing a vector.
        Called by MicrologWorker, never by the router.
        Returns count of records processed.
        """
        pending = self._repo.get_unembedded(limit=limit)
        if not pending:
            return 0
        for row in pending:
            vector = self._embedder.embed_text(row["content"])
            self._repo.update_embedding(row["id"], vector)
        logger.info("Embedded %d micrologs", len(pending))
        return len(pending)