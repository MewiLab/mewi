"""
Unit tests for Pydantic domain models.

Validates field constraints, defaults, and serialization.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.microlog import MicrologCreate, MicrologInDB, MicrologRead, MicrologUpdate


class TestMicrologCreate:
    def test_valid_payload(self):
        m = MicrologCreate(user_id=uuid4(), content="hello")
        assert m.valence == 0.0
        assert m.arousal == 0.0

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            MicrologCreate(user_id=uuid4(), content="")

    def test_valence_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            MicrologCreate(user_id=uuid4(), content="hi", valence=1.5)

    def test_arousal_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            MicrologCreate(user_id=uuid4(), content="hi", arousal=-2.0)

    def test_optional_urls_default_none(self):
        m = MicrologCreate(user_id=uuid4(), content="test")
        assert m.image_url is None
        assert m.video_url is None
        assert m.voice_url is None


class TestMicrologInDB:
    def test_inherits_create_fields_plus_embedding(self):
        m = MicrologInDB(
            user_id=uuid4(),
            content="hello",
            embedding=[0.1, 0.2, 0.3],
        )
        assert m.embedding == [0.1, 0.2, 0.3]
        assert m.reply is None

    def test_embedding_defaults_to_none(self):
        m = MicrologInDB(user_id=uuid4(), content="hi")
        assert m.embedding is None


class TestMicrologUpdate:
    def test_partial_update_reply_only(self):
        patch = MicrologUpdate(reply="喵～")
        dump = patch.model_dump(exclude_none=True)
        assert dump == {"reply": "喵～"}

    def test_empty_update_dumps_nothing(self):
        patch = MicrologUpdate()
        dump = patch.model_dump(exclude_none=True)
        assert dump == {}
