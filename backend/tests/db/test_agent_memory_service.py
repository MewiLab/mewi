"""
Tests for EmbeddingService — mocks OpenAI so no API key is needed.

Replaces the old AgentMemoryService tests; embedding is now handled
by EmbeddingService(settings).embed_text(text).
"""
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import Settings
from app.core.exceptions import EmbeddingError
from app.services.embedding import EmbeddingService


FAKE_EMBEDDING = [0.1] * 1536


@pytest.fixture
def settings():
    return Settings(
        supabase_url="http://fake",
        supabase_key="fake-key",
        openai_api_key="fake-openai-key",
    )


@pytest.fixture
def mock_openai_response():
    mock_resp = MagicMock()
    mock_resp.data[0].embedding = FAKE_EMBEDDING
    return mock_resp


class TestEmbeddingService:
    def test_embed_text_returns_vector(self, settings, mock_openai_response):
        svc = EmbeddingService(settings)
        with patch.object(svc._client.embeddings, "create", return_value=mock_openai_response):
            result = svc.embed_text("今天心情很好！")
        assert result == FAKE_EMBEDDING

    def test_embed_text_calls_correct_model(self, settings, mock_openai_response):
        svc = EmbeddingService(settings)
        with patch.object(svc._client.embeddings, "create", return_value=mock_openai_response) as mock_create:
            svc.embed_text("test")
        mock_create.assert_called_once_with(input="test", model="text-embedding-3-small")

    def test_empty_text_returns_empty_list(self, settings):
        svc = EmbeddingService(settings)
        result = svc.embed_text("   ")
        assert result == []

    def test_blank_string_skips_openai(self, settings):
        svc = EmbeddingService(settings)
        with patch.object(svc._client.embeddings, "create") as mock_create:
            result = svc.embed_text("")
        assert result == []
        mock_create.assert_not_called()

    def test_openai_error_raises_embedding_error(self, settings):
        svc = EmbeddingService(settings)
        with patch.object(svc._client.embeddings, "create", side_effect=RuntimeError("API down")):
            with pytest.raises(EmbeddingError):
                svc.embed_text("some content")
