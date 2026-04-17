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

        # base_url: only use explicit EMBEDDING_BASE_URL — no Ollama fallback.
        # Generative Ollama models (e.g. gemma3:27b) return 501 on /embeddings.
        # Set EMBEDDING_BASE_URL explicitly if you want a non-OpenAI embedding endpoint.
        base_url: str | None = emb.base_url or None

        # api_key: embedding key → LLM key → bare OPENAI_API_KEY → "ollama" placeholder
        api_key = emb.api_key or settings.llm.api_key or settings.openai_api_key or "ollama"

        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            return []
        try:
            response = self._client.embeddings.create(input=text, model=self._model)
            return response.data[0].embedding
        except Exception as exc:
            logger.error("Embedding error: %s", exc)
            raise EmbeddingError(str(exc)) from exc