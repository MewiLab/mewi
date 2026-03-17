from pydantic import BaseModel
from typing import Optional, List

class GroundTruth(BaseModel):
    valence: float
    arousal: float

# MicroLog structure.
class ScentData(BaseModel):
    id: int
    user_id: str = "test_user_01"  # 預設一個 ID
    text: str
    lbs_context: Optional[str] = None
    ground_truth: GroundTruth
    routing_label: str
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    voice_url: Optional[str] = None

    class Config:
        # 允許從資料庫物件直接轉換 (用於 SupaBase)
        from_attributes = True