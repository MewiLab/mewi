from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID

class MicrologSchema(BaseModel):
    """微日記模型：處理文字、情緒值、多媒體 URL 與向量"""
    id: Optional[UUID] = None
    userId: UUID = Field(..., alias="user_id")
    content: str
    valence: float = 0.0
    arousal: float = 0.0
    imageUrl: Optional[str] = Field(None, alias="image_url")
    videoUrl: Optional[str] = Field(None, alias="video_url")
    voiceUrl: Optional[str] = Field(None, alias="voice_url")
    embedding: Optional[List[float]] = None 
    reply: Optional[str] = None
    createdAt: Optional[datetime] = Field(None, alias="created_at")

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "user_id": "00000000-0000-0000-0000-000000000000",
                "content": "今天心情不錯",
                "valence": 0.8,
                "arousal": 0.2,
                "image_url": "https://example.com/image.jpg"
            }
        }

class UserSchema(BaseModel):
    """使用者基本資料模型"""
    id: UUID
    aura: Optional[str] = None
    movement: Optional[str] = None
    identity: Optional[str] = None
    createdAt: datetime = Field(..., alias="created_at")

    class Config:
        populate_by_name = True

class UserCreatureRelationSchema(BaseModel):
    """使用者與生物(Agent)之間的關係與記憶模型"""
    id: UUID
    userId: UUID = Field(..., alias="user_id")
    creatureId: UUID = Field(..., alias="creature_id")
    bondScore: int = Field(0, alias="bond_score")
    episodicMemories: List[str] = Field([], alias="episodic_memories")
    emotionalTags: List[str] = Field([], alias="emotional_tags")
    lastSeenAt: Optional[datetime] = Field(None, alias="last_seen_at")
    
    class Config:
        populate_by_name = True