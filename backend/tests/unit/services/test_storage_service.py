"""
Unit tests for StorageService.

Supabase Storage is fully mocked — no real bucket needed.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO

from fastapi import UploadFile

from app.core.exceptions import StorageError
from app.services.storage import StorageService


@pytest.fixture
def mock_upload_file():
    """Fake UploadFile that returns bytes on read()."""
    file = AsyncMock(spec=UploadFile)
    file.filename = "cat_photo.png"
    file.content_type = "image/png"
    file.read.return_value = b"fake-image-bytes"
    return file


@pytest.fixture
def mock_storage_client():
    """Supabase client with mocked .storage.from_() chain."""
    client = MagicMock()
    bucket = MagicMock()
    bucket.upload.return_value = None
    bucket.get_public_url.return_value = "https://cdn.example.com/img.png"
    client.storage.from_.return_value = bucket
    return client


class TestUpload:
    async def test_returns_public_url(self, mock_storage_client, mock_upload_file):
        svc = StorageService(mock_storage_client)
        url = await svc.upload("user-1", mock_upload_file, "image")
        assert url == "https://cdn.example.com/img.png"

    async def test_reads_file_bytes(self, mock_storage_client, mock_upload_file):
        svc = StorageService(mock_storage_client)
        await svc.upload("user-1", mock_upload_file, "image")
        mock_upload_file.read.assert_called_once()

    async def test_uploads_to_correct_bucket(self, mock_storage_client, mock_upload_file):
        svc = StorageService(mock_storage_client)
        await svc.upload("user-1", mock_upload_file, "image")
        mock_storage_client.storage.from_.assert_called_with("micrologs-media")

    async def test_path_includes_user_id_and_media_type(self, mock_storage_client, mock_upload_file):
        svc = StorageService(mock_storage_client)
        await svc.upload("user-42", mock_upload_file, "voice")
        bucket = mock_storage_client.storage.from_.return_value
        upload_call = bucket.upload.call_args
        path = upload_call.kwargs.get("path") or upload_call[1].get("path")
        assert path.startswith("user-42/voices/")
        assert path.endswith(".png")

    async def test_storage_failure_raises_storage_error(self, mock_upload_file):
        client = MagicMock()
        client.storage.from_.return_value.upload.side_effect = RuntimeError("bucket gone")
        svc = StorageService(client)
        with pytest.raises(StorageError):
            await svc.upload("user-1", mock_upload_file, "image")
