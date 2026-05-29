"""Models for the Unity agent websocket tick envelope."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Location(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class SelfState(BaseModel):
    location:       Location | str = ""
    current_action: str            = "idle"
    location_label: str            = ""


class MoodState(BaseModel):
    fear:      float = Field(0.0, ge=0.0, le=1.0)
    trust:     float = Field(0.0, ge=0.0, le=1.0)
    curiosity: float = Field(0.5, ge=0.0, le=1.0)
    social:    float = Field(0.0, ge=0.0, le=1.0)
    energy:    float = Field(1.0, ge=0.0, le=1.0)


class HealthState(BaseModel):
    fullness: float = Field(1.0, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_hunger(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "fullness" in value or "hunger" not in value:
            return value
        try:
            hunger = float(value.get("hunger") or 0.0)
        except (TypeError, ValueError):
            hunger = 0.0
        return {**value, "fullness": max(0.0, min(1.0, 1.0 - hunger))}


class EntitySnapshot(BaseModel):
    id:        str       = ""
    tags:      list[str] = Field(default_factory=list)
    distance:  float     = 0.0
    direction: str       = ""


class ZoneEntry(BaseModel):
    id:          str = ""
    type:        str = ""
    confinement: str = ""
    surface:     str = ""


class SpatialContext(BaseModel):
    zones: list[ZoneEntry] = Field(default_factory=list)


class PlaceContext(BaseModel):
    current_zone_id: str = ""
    active_zone_ids: list[str] = Field(default_factory=list)
    reachable_zone_ids: list[str] = Field(default_factory=list)


class FeelingsData(BaseModel):
    summary: str = ""
    smells:  list[str] = Field(default_factory=list)
    sounds:  list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)


class TickPayload(BaseModel):
    """
    One full environment snapshot pushed from Unity over the agent websocket.

    creature_id is a websocket path parameter, not part of the sensor payload.
    The incoming JSON key "self" is mapped to `self_state` to avoid the
    Python keyword; callers serialise back with by_alias=True.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    request_id: str                  = Field("",  alias="requestId")
    agent_id:   str                  = ""
    command_id: str                  = Field("", alias="commandId")
    time:       float | None         = None
    self_state: SelfState            = Field(default_factory=SelfState, alias="self")
    mood:       MoodState            = Field(default_factory=MoodState)
    health:     HealthState          = Field(default_factory=HealthState)
    entities:   list[EntitySnapshot] = Field(default_factory=list)
    spatial_context: SpatialContext  = Field(default_factory=SpatialContext)
    place_context: PlaceContext      = Field(default_factory=PlaceContext)
    feelings:   FeelingsData         = Field(default_factory=FeelingsData)
    action_result: dict[str, Any] | None = None
