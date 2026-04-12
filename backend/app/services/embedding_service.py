# app/services/embedding_service.py
"""
Embedding service — wraps any OpenAI-compatible embeddings endpoint.

Follows the same provider pattern as LLMSettings:
  EMBEDDING_PROVIDER=openai       (default)
  EMBEDDING_PROVIDER=openrouter
  EMBEDDING_MODEL=text-embedding-3-small
"""

import logging
from openai import OpenAI

from app.core.config import Settings
from app.core.exceptions import EmbeddingError

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, settings: Settings):
        emb = settings.embedding            
        self._model = emb.model
        self._client = OpenAI(
            api_key=emb.api_key or settings.llm.api_key,   # fall back to LLM key
            base_url=emb.base_url or None,
        )

    def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            return []
        try:
            response = self._client.embeddings.create(input=text, model=self._model)
            return response.data[0].embedding
        except Exception as exc:
            logger.error("Embedding error: %s", exc)
            raise EmbeddingError(str(exc)) from exc