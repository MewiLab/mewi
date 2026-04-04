"""
Media storage service — uploads files to Supabase Storage.
"""

import uuid
import logging

from fastapi import UploadFile
from supabase import Client

from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)

BUCKET = "micrologs-media"


class StorageService:
    def __init__(self, supabase: Client):
        self._db = supabase

    async def upload(self, user_id: str, file: UploadFile, media_type: str) -> str:
        """Upload a file and return its public URL."""
        try:
            file_bytes = await file.read()
            ext = file.filename.rsplit(".", 1)[-1] if file.filename else "bin"
            path = f"{user_id}/{media_type}s/{uuid.uuid4()}.{ext}"

            self._db.storage.from_(BUCKET).upload(
                file=file_bytes,
                path=path,
                file_options={"content-type": file.content_type or "application/octet-stream"},
            )
            return self._db.storage.from_(BUCKET).get_public_url(path)

        except Exception as exc:
            logger.error("Storage upload error: %s", exc)
            raise StorageError(str(exc)) from exc