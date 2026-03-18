from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID

class MicrologSchema(BaseModel):
    # 改為 Optional，且預設為 None，避免 FastAPI 強制生成一個不符合 DB 邏輯的值
    id: Optional[UUID] = None
    userId: UUID = Field(..., alias="user_id")
    content: str
    valence: float = 0.0
    arousal: float = 0.0
    imageUrl: Optional[str] = Field(None, alias="image_url")
    videoUrl: Optional[str] = Field(None, alias="video_url")
    voiceUrl: Optional[str] = Field(None, alias="voice_url")
    
    embedding: Optional[List[float]] = None 
    
    # 這裡移除 default_factory，交給資料庫處理
    createdAt: Optional[datetime] = Field(None, alias="created_at")

    class Config:
        populate_by_name = True
        # 增加一個範例，方便 Swagger 測試
        json_schema_extra = {
            "example": {
                "user_id": "00000000-0000-0000-0000-000000000000",
                "content": "輸入文本...",
                "valence": 0.8,
                "arousal": 0.2,
                "image_url": "https://example.com/image.jpg"
            }
        }

class UserSchema(BaseModel):
    id: UUID
    aura: Optional[str] = None
    movement: Optional[str] = None
    identity: Optional[str] = None
    createdAt: datetime = Field(..., alias="created_at")

    class Config:
        populate_by_name = True

class UserCreatureRelationSchema(BaseModel):
    id: UUID
    userId: UUID = Field(..., alias="user_id")
    creatureId: UUID = Field(..., alias="creature_id")
    bondScore: int = Field(0, alias="bond_score")
    episodicMemories: List[str] = Field([], alias="episodic_memories")
    emotionalTags: List[str] = Field([], alias="emotional_tags")
    lastSeenAt: Optional[datetime] = Field(None, alias="last_seen_at")
    
    class Config:
        populate_by_name = True