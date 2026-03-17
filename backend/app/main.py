from fastapi import FastAPI, Query
from typing import List
from app.schemas import ScentData
from app.services import get_scent_samples

app = FastAPI(
    title="MEW 氣味語料供應 API",
    description="提供給 Unity 或 VA 模型開發使用的測試資料集分發站",
    version="1.1.0"
)

@app.get("/api/v1/micrologs/{user_id}", response_model=List[ScentData], summary="根據用戶 ID 獲取日記資料")
async def getMicrologByUserId(
    user_id: str,
    count: int = Query(10, description="想要獲取的資料筆數", ge=1, le=100),
    category: str = Query("edge", description="分類 (edge/cloud)"),
    mode: str = Query("short", description="長度 (short/long)")
):
    """
    獲取指定用戶的日記資料：
    - **user_id**: 用戶唯一識別碼
    - **count**: 筆數
    - **category**: edge/cloud
    - **mode**: short/long
    """
    # 呼叫邏輯層獲取資料
    samples = await get_scent_samples(count, category, mode)
    
    # 手動補上 user_id（因為目前 JSON 裡可能沒有這個欄位）
    for s in samples:
        s["user_id"] = user_id
        
    return samples