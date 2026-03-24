"""User & creature-relation domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreatureRead(BaseModel):
    id: UUID
    aura: list[str]|None = None
    movement: list[str]|None = None
    identity: list[str]|None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BetweenCreatureRelationRead(BaseModel):
    id: UUID
    user_id: UUID
    creature_id: UUID
    bond_score: int = 0
    episodic_memories: list[str] = Field(default_factory=list)
    emotional_tags: list[str] = Field(default_factory=list)
    last_seen_at: list[datetime] = None

    model_config = {"from_attributes": True}
