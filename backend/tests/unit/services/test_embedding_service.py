"""
Unit tests for EmbeddingService.

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


class TestEmbedText:
    def test_returns_vector(self, svc, mock_openai_response):
        with patch.object(svc._client.embeddings, "create", return_value=mock_openai_response):
            result = svc.embed_text("今天心情很好！")
        assert result == FAKE_VECTOR
        assert len(result) == 1536

    def test_calls_correct_model(self, svc, mock_openai_response):
        with patch.object(svc._client.embeddings, "create", return_value=mock_openai_response) as mock_create:
            svc.embed_text("test input")
        mock_create.assert_called_once_with(input="test input", model="text-embedding-3-small")

    def test_empty_string_returns_empty_list(self, svc):
        assert svc.embed_text("") == []

    def test_whitespace_only_returns_empty_list(self, svc):
        assert svc.embed_text("   \n\t  ") == []

    def test_blank_input_skips_openai_call(self, svc):
        with patch.object(svc._client.embeddings, "create") as mock_create:
            svc.embed_text("")
        mock_create.assert_not_called()

    def test_openai_failure_raises_embedding_error(self, svc):
        with patch.object(svc._client.embeddings, "create", side_effect=RuntimeError("API down")):
            with pytest.raises(EmbeddingError):
                svc.embed_text("some content")
