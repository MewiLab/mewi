"""
Integration test: verify OpenAI embedding with real API key.

Marked @paid — each call costs ~$0.0001.
Only runs with `make test-all CONFIRM_PAID=1`.
"""

import pytest

from app.services.embedding import EmbeddingService


@pytest.mark.paid
class TestEmbeddingReal:
    def test_returns_1536_dim_vector(self, real_settings):
        svc = EmbeddingService(real_settings)
        vector = svc.embed_text("今天天氣真好，看到好多流浪貓！")
        assert isinstance(vector, list)
        assert len(vector) == 1536
        assert all(isinstance(v, float) for v in vector)

    def test_different_texts_produce_different_vectors(self, real_settings):
        svc = EmbeddingService(real_settings)
        v1 = svc.embed_text("我很開心")
        v2 = svc.embed_text("我很難過")
        assert v1 != v2

    def test_empty_text_skips_api(self, real_settings):
        svc = EmbeddingService(real_settings)
        result = svc.embed_text("")
        assert result == []
