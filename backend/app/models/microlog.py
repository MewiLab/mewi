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
    image_url: str | None = None
    video_url: str | None = None
    voice_url: str | None = None


# ── Internal (enriched before DB write) ──────────────────────
class MicrologInDB(MicrologCreate):
    embedding: list[float] | None = None
    reply: str | None = None


# ── Outgoing (returned to client) ────────────────────────────
class MicrologRead(BaseModel):
    id: UUID
    user_id: UUID
    content: str
    valence: float
    arousal: float
    image_url: str | None = None
    video_url: str | None = None
    voice_url: str | None = None
    reply: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Partial update ───────────────────────────────────────────
class MicrologUpdate(BaseModel):
    reply: str | None = None
    valence: float | None = None
    arousal: float | None = None