from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.services.storage_service import StorageService
from enum import Enum

router = APIRouter()

class MediaType(str, Enum):
    image = "image"
    video = "video"
    voice = "voice"

@router.post("/upload", summary="上傳多媒體檔案至 Supabase Storage")
async def upload_media(
    user_id: str = Form(...),
    media_type: MediaType = Form(...),
    file: UploadFile = File(...)
):
    try:
        url = await StorageService.upload_file(user_id, file, media_type.value)
        return {"status": "success", "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))