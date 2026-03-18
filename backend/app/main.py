from fastapi import FastAPI, Query, HTTPException
from typing import List
from uuid import UUID
from app.schemas import MicrologSchema
from app.repositories.microlog_repository import MicrologRepository

app = FastAPI(
    title="MEW Backend API",
    description="MEW 核心後端：支援 Unity 與 AI Agent 的記憶存取系統",
    version="2.0.0"
)

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
@app.post("/api/v1/micrologs", summary="新增一筆日記資料")
async def create_microlog(log_data: MicrologSchema):
    """
    接收 Unity 傳來的日記 JSON，包含文字、V/A 座標與多媒體 URL
    """
    try:
        result = MicrologRepository.create_microlog(log_data)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"存檔失敗: {str(e)}")

@app.get("/")
def read_root():
    return {"message": "MEW API v2.0 is online!"}