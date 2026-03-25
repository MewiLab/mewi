"""User & creature-relation domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserRead(BaseModel):
    id: UUID
    aura: str | None = None
    movement: str | None = None
    identity: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreatureRelationRead(BaseModel):
    id: UUID
    user_id: UUID
    creature_id: UUID
    bond_score: int = 0
    episodic_memories: list[str] = Field(default_factory=list)
    emotional_tags: list[str] = Field(default_factory=list)
    last_seen_at: datetime | None = None

    model_config = {"from_attributes": True}