"""
/assets routes — media upload endpoints.
"""

from enum import Enum

from fastapi import APIRouter, File, Form, UploadFile

from app.api.deps import SupabaseDep
from app.services.storage import StorageService

router = APIRouter(prefix="/assets", tags=["assets"])

class MediaType(str, Enum):
    image = "image"
    video = "video"
    voice = "voice"
    
@router.post("/upload")
async def upload_media(
    db: SupabaseDep,
    user_id: str = Form(...),
    media_type: MediaType = Form(...),
    file: UploadFile = File(...),
):
    """Upload a media file to Supabase Storage and return its public URL."""
    svc = StorageService(db)
    url = await svc.upload(user_id, file, media_type.value)
    return {"status": "success", "url": url}