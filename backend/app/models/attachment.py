from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CatAssignedType(StrEnum):
    SECURE = "secure"
    ANXIOUS = "anxious"
    AVOIDANT = "avoidant"
    DISORGANIZED = "disorganized"


class AttachmentEventType(StrEnum):
    CAT_WITHDREW = "cat_withdrew"
    CAT_SOUGHT_PLAYER = "cat_sought_player"
    PLAYER_APPROACHED = "player_approached"
    PLAYER_RETREATED = "player_retreated"
    PLAYER_RETURNED_AFTER_ABSENCE = "player_returned_after_absence"
    PLAYER_LEFT = "player_left"
    PLAYER_NEAR = "player_near"
    PLAYER_FAR = "player_far"
    PLAYER_INTERACTED = "player_interacted"


class PlayerAttachmentEstimate(StrEnum):
    SECURE = "secure"
    ANXIOUS = "anxious"
    AVOIDANT = "avoidant"
    DISORGANIZED = "disorganized"
    UNDETERMINED = "undetermined"


class AttachmentConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RawAttachmentEvent(BaseModel):
    """One fully qualified Unity interaction event."""

    model_config = ConfigDict(extra="allow")

    session_id: UUID
    cat_id: str
    event: AttachmentEventType
    t: float = Field(ge=0.0)
    distance: float | None = Field(default=None, ge=0.0)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cat_id")
    @classmethod
    def _cat_id_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("cat_id is required")
        return value

class AttachmentEventInput(BaseModel):
    """Compact event shape accepted by the endpoint.

    Unity may omit session_id/cat_id per event when those are already present
    on the enclosing session payload.
    """

    model_config = ConfigDict(extra="allow")

    session_id: UUID | None = None
    cat_id: str | None = None
    event: AttachmentEventType
    t: float = Field(ge=0.0)
    distance: float | None = Field(default=None, ge=0.0)
    meta: dict[str, Any] = Field(default_factory=dict)


class AttachmentSessionPayload(BaseModel):
    session_id: UUID
    cat_id: str
    cat_assigned_type: CatAssignedType
    events: list[AttachmentEventInput] = Field(default_factory=list, min_length=1)

    @field_validator("cat_id")
    @classmethod
    def _cat_id_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("cat_id is required")
        return value

    @model_validator(mode="after")
    def _events_match_session(self) -> "AttachmentSessionPayload":
        for event in self.events:
            if event.session_id is not None and event.session_id != self.session_id:
                raise ValueError("event.session_id must match payload.session_id")
            if event.cat_id is not None and event.cat_id.strip() != self.cat_id:
                raise ValueError("event.cat_id must match payload.cat_id")
        return self

    def raw_events(self) -> list[RawAttachmentEvent]:
        events: list[RawAttachmentEvent] = []
        for event in self.events:
            events.append(RawAttachmentEvent(
                session_id=event.session_id or self.session_id,
                cat_id=(event.cat_id or self.cat_id).strip(),
                event=event.event,
                t=event.t,
                distance=event.distance,
                meta=event.meta,
            ))
        return events


class AttachmentSessionFeatures(BaseModel):
    session_id: UUID
    cat_id: str
    cat_assigned_type: CatAssignedType
    reapproach_latency_mean: float = 0.0
    pursuit_ratio: float = 0.0
    time_near_ratio: float = 0.0
    reunion_response: float = 0.0
    withdrawal_tolerance: float = 0.0
    n_events: int = 0


class AttachmentAnalysisResult(BaseModel):
    session_id: UUID
    cat_id: str
    cat_assigned_type: CatAssignedType
    player_attachment_estimate: PlayerAttachmentEstimate
    scores: dict[str, float]
    confidence: AttachmentConfidence = AttachmentConfidence.LOW
    n_events: int
    features: AttachmentSessionFeatures
    rule_trace: list[str] = Field(default_factory=list)
