"""
Microlog domain models.

Separating Create / Read / Update prevents:
  - users injecting 'id' or 'created_at' on create
  - internal fields (embedding) leaking in API responses
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Incoming (from Unity client) ─────────────────────────────
class MicrologCreate(BaseModel):
    user_id: UUID
    content: str = Field(..., min_length=1, max_length=5000)
    valence: float = Field(0.0, ge=-1.0, le=1.0)
    arousal: float = Field(0.0, ge=-1.0, le=1.0)
    image_url: str|None = None
    video_url: str|None = None
    voice_url: str|None = None


# ── Internal (enriched before DB write) ──────────────────────
class MicrologInDB(MicrologCreate):
    embedding: list[float]|None = None
    reply: str|None = None


# ── Outgoing (returned to client) ────────────────────────────
class MicrologRead(BaseModel):
    id: UUID
    user_id: UUID
    content: str
    valence: float
    arousal: float
    image_url: str|None = None
    video_url: str|None = None
    voice_url: str|None = None
    reply: str|None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Partial update ───────────────────────────────────────────
class MicrologUpdate(BaseModel):
    reply: str|None = None
    valence: float|None = None
    arousal: float|None = None



# from pydantic import BaseModel, Field
# from typing import List, Optional
# from datetime import datetime
# from uuid import UUID

class Microlog(BaseModel):
    """微日記模型：處理文字、情緒值、多媒體 URL 與向量"""
    id: UUID|None = None
    userId: UUID = Field(..., alias="user_id")
    content: str
    valence: float = 0.0
    arousal: float = 0.0
    imageUrl: str|None = Field(None, alias="image_url")
    videoUrl: str|None = Field(None, alias="video_url")
    voiceUrl: str|None = Field(None, alias="voice_url")
    embedding: list[float]|None = None 
    reply: str|None = None
    createdAt: datetime|None = Field(None, alias="created_at")

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