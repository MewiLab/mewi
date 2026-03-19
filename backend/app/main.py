from fastapi import FastAPI, Query, HTTPException
from typing import List
from uuid import UUID
from app.schemas import MicrologSchema
from app.repositories.microlog_repository import MicrologRepository
from app.services import AgentMemoryService, StorageService
from enum import Enum
from fastapi import FastAPI, Query, HTTPException, UploadFile, File, Form

app = FastAPI(
    title="MEW Backend API",
    description="MEW 核心後端：支援 Unity 與 AI Agent 的記憶存取系統",
    version="2.0.0"
)

class MediaType(str, Enum):
    image = "image"
    video = "video"
    voice = "voice"

# GET diary
@app.get("/api/v1/micrologs/{user_id}", response_model=List[MicrologSchema], summary="根據用戶 ID 獲取日記資料")
async def get_micrologs_by_user(
    user_id: UUID,
    count: int = Query(10, description="想要獲取的資料筆數", ge=1, le=100)
):
    """
    從 Supabase 獲取指定用戶的日記資料：
    - **user_id**: 用戶 UUID
    - **count**: 想要回傳的筆數 (預設 10 筆)
    """
    try:
        # call repositories
        samples = MicrologRepository.get_user_logs(str(user_id), limit=count)
        
        if not samples:
            return []
            
        return samples
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料庫讀取失敗: {str(e)}")

# POST for Unity
@app.post("/api/v1/micrologs", summary="新增一筆日記資料，並生成語意向量")
async def create_microlog(log_data: MicrologSchema):
    """
    接收 Unity 傳來的日記 JSON，包含文字、V/A 座標與多媒體 URL
    系統會在背景呼叫 OpenAI 將內容轉為 1536 維的向量，再存入 Supabase pgvector。
    """
    try:
        # 1. 攔截資料：請 OpenAI 算出這句話的向量座標
        processed_data = AgentMemoryService.process_new_microlog(log_data)
        
        # 2. 存入資料庫：直接交給你寫好的 Repository
        result = MicrologRepository.create_microlog(processed_data)

        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"存檔失敗: {str(e)}")

# POST for file upload
@app.post("/api/v1/upload", summary="上傳多媒體檔案 (圖片/影片/聲音)")
async def upload_media(
    user_id: str = Form(..., description="用戶 ID"),
    media_type: MediaType = Form(..., description="媒體類型 (image/video/voice)"),
    file: UploadFile = File(..., description="要上傳的檔案")
):
    """
    統一的檔案上傳入口。
    """
    content_type = file.content_type.lower()
    if media_type == MediaType.image and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="請上傳圖片格式檔案")
    elif media_type == MediaType.video and not content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="請上傳影片格式檔案")
    elif media_type == MediaType.voice and not content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="請上傳音檔格式檔案")
    
    try:
        public_url = await StorageService.upload_file(user_id, file, media_type.value)
        return {
            "status": "success", 
            "message": f"{media_type.value} 上傳成功",
            f"{media_type.value}_url": public_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"message": "MEW API v2.0 is online!"}