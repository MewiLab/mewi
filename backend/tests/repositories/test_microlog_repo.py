"""
Unit tests for MicrologRepository.

Supabase client is fully mocked — no real DB needed.
"""

from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import DatabaseError, NotFoundError
from app.models.microlog import MicrologInDB, MicrologUpdate
from app.repositories.microlog_repo import MicrologRepository


FAKE_USER_ID = uuid4()

FAKE_ROW = {
    "id": str(uuid4()),
    "user_id": str(FAKE_USER_ID),
    "content": "今天遇到一隻橘貓",
    "valence": 0.6,
    "arousal": 0.3,
    "image_url": None,
    "video_url": None,
    "voice_url": None,
    "reply": None,
    "created_at": "2025-01-01T00:00:00Z",
}


class TestCreate:
    def test_returns_inserted_row(self, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=[FAKE_ROW])
        repo = MicrologRepository(mock_supabase)
        data = MicrologInDB(
            user_id=FAKE_USER_ID,
            content="今天遇到一隻橘貓",
            valence=0.6,
            arousal=0.3,
        )
        result = repo.create(data)
        assert result["content"] == "今天遇到一隻橘貓"
        mock_supabase.table.assert_called_with("micrologs")

    def test_empty_response_raises_database_error(self, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=[])
        repo = MicrologRepository(mock_supabase)
        data = MicrologInDB(user_id=FAKE_USER_ID, content="test")
        with pytest.raises(DatabaseError):
            repo.create(data)

    def test_api_error_raises_database_error(self, mock_supabase):
        from postgrest.exceptions import APIError

        mock_supabase._builder.execute.side_effect = APIError({"message": "conflict", "code": "23505", "details": "", "hint": ""})
        repo = MicrologRepository(mock_supabase)
        data = MicrologInDB(user_id=FAKE_USER_ID, content="test")
        with pytest.raises(DatabaseError):
            repo.create(data)


class TestUpdate:
    def test_returns_updated_row(self, mock_supabase):
        updated_row = {**FAKE_ROW, "reply": "喵～"}
        mock_supabase._builder.execute.return_value = MagicMock(data=[updated_row])
        repo = MicrologRepository(mock_supabase)
        result = repo.update(FAKE_ROW["id"], MicrologUpdate(reply="喵～"))
        assert result["reply"] == "喵～"

    def test_missing_id_raises_not_found(self, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=[])
        repo = MicrologRepository(mock_supabase)
        with pytest.raises(NotFoundError):
            repo.update("nonexistent-id", MicrologUpdate(reply="hi"))


class TestGetByUser:
    def test_returns_list_of_rows(self, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=[FAKE_ROW, FAKE_ROW])
        repo = MicrologRepository(mock_supabase)
        result = repo.get_by_user(str(FAKE_USER_ID), limit=10)
        assert len(result) == 2

    def test_empty_user_returns_empty_list(self, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=[])
        repo = MicrologRepository(mock_supabase)
        result = repo.get_by_user(str(uuid4()))
        assert result == []


class TestGetById:
    def test_returns_single_row(self, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=FAKE_ROW)
        repo = MicrologRepository(mock_supabase)
        result = repo.get_by_id(FAKE_ROW["id"])
        assert result["content"] == "今天遇到一隻橘貓"

    def test_missing_id_returns_none(self, mock_supabase):
        mock_supabase._builder.execute.return_value = MagicMock(data=None)
        repo = MicrologRepository(mock_supabase)
        result = repo.get_by_id("nonexistent")
        assert result is None
