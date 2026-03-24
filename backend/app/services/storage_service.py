import uuid
from fastapi import UploadFile
from app.db.base import supabase

class StorageService:
    BUCKET_NAME = "micrologs-media"

    @classmethod
    async def upload_file(cls, user_id: str, file: UploadFile, media_type: str) -> str:
        try:
            file_bytes = await file.read()
            file_extension = file.filename.split(".")[-1]
            unique_filename = f"{user_id}/{media_type}s/{uuid.uuid4()}.{file_extension}"
            
            supabase.storage.from_(cls.BUCKET_NAME).upload(
                file=file_bytes,
                path=unique_filename,
                file_options={"content-type": file.content_type}
            )
            return supabase.storage.from_(cls.BUCKET_NAME).get_public_url(unique_filename)
        except Exception as e:
            raise Exception(f"Upload Failed: {str(e)}")