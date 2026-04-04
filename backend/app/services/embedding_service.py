"""
Embedding service — wraps the OpenAI embeddings API.

Stateless: receives the API key from Settings so it's easy to swap
providers or mock in tests.
"""

import logging

from openai import OpenAI

from app.core.config import Settings
from app.core.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"


class EmbeddingService:
    def __init__(self, settings: Settings):
        self._client = OpenAI(api_key=settings.openai_api_key)

    def embed_text(self, text: str) -> list[float]:
        """Return the embedding vector for a single text string."""
        if not text or not text.strip():
            return []

        try:
            response = self._client.embeddings.create(input=text, model=MODEL)
            return response.data[0].embedding
        except Exception as exc:
            logger.error("OpenAI embedding error: %s", exc)
            raise EmbeddingError(str(exc)) from exc