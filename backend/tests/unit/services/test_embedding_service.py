"""
Unit tests for EmbeddingService.

Uses shared fixtures from tests/conftest.py: settings
All OpenAI calls are mocked — no API key needed, no cost.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.core.exceptions import EmbeddingError
from app.services.embedding_service import EmbeddingService


FAKE_VECTOR = [0.1] * 1536


@pytest.fixture
def svc(settings):
    return EmbeddingService(settings)


@pytest.fixture
def mock_openai_response():
    resp = MagicMock()
    resp.data = [MagicMock(embedding=FAKE_VECTOR)]
    return resp


# ── embed_text ────────────────────────────────────────────────────────────────

class TestEmbedText:
    def test_returns_vector(self, svc, mock_openai_response):
        with patch.object(svc._client.embeddings, "create", return_value=mock_openai_response):
            result = svc.embed_text("今天心情很好！")
        assert result == FAKE_VECTOR
        assert len(result) == 1536

    def test_calls_correct_model(self, svc, mock_openai_response, settings):
        with patch.object(
            svc._client.embeddings, "create", return_value=mock_openai_response
        ) as mock_create:
            svc.embed_text("test input")
        mock_create.assert_called_once_with(
            input="test input",
            model=settings.embedding.model,   # from settings, not hardcoded
        )

    def test_empty_string_returns_empty_list(self, svc):
        assert svc.embed_text("") == []

    def test_whitespace_only_returns_empty_list(self, svc):
        assert svc.embed_text("   \n\t  ") == []

    def test_blank_input_skips_api_call(self, svc):
        with patch.object(svc._client.embeddings, "create") as mock_create:
            svc.embed_text("   ")
        mock_create.assert_not_called()

    def test_api_failure_raises_embedding_error(self, svc):
        with patch.object(
            svc._client.embeddings, "create", side_effect=RuntimeError("API down")
        ):
            with pytest.raises(EmbeddingError):
                svc.embed_text("some content")

    def test_embedding_error_preserves_original_cause(self, svc):
        original = RuntimeError("timeout")
        with patch.object(svc._client.embeddings, "create", side_effect=original):
            with pytest.raises(EmbeddingError) as exc_info:
                svc.embed_text("some content")
        assert exc_info.value.__cause__ is original


# ── constructor ───────────────────────────────────────────────────────────────

class TestEmbeddingServiceInit:
    def test_falls_back_to_llm_key_when_embedding_key_empty(self, settings):
        settings.embedding.api_key = ""
        settings.llm.api_key = "llm-key-123"
        svc = EmbeddingService(settings)
        assert svc._client.api_key == "llm-key-123"

    def test_uses_embedding_key_when_set(self, settings):
        settings.embedding.api_key = "emb-key-456"
        svc = EmbeddingService(settings)
        assert svc._client.api_key == "emb-key-456"

    def test_model_comes_from_settings(self, settings):
        settings.embedding.model = "text-embedding-3-large"
        svc = EmbeddingService(settings)
        assert svc._model == "text-embedding-3-large"