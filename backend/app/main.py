from fastapi import FastAPI, Query
from typing import List
from app.schemas import ScentData
from app.services import get_scent_samples

app = FastAPI(
    title="MEW 氣味語料供應 API",
    description="提供給 Unity 或 VA 模型開發使用的測試資料集分發站",
    version="1.0.0"
)

@app.get("/api/v1/data", response_model=List[ScentData], summary="獲取指定數量的氣味資料")
async def read_data(
    count: int = Query(10, description="想要獲取的資料筆數", ge=1, le=100),
    category: str = Query("edge", description="分類 (edge/cloud)"),
    mode: str = Query("short", description="長度 (short/long)")
):
    """
    這是一個彈性的資料獲取路徑：
    - **count**: 你想要幾筆？
    - **category**: 要 Edge 還是 Cloud？
    - **mode**: 要 Short 還是 Long？
    """
    samples = await get_scent_samples(count, category, mode)
    return samples