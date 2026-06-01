"""Models for the Unity agent websocket tick envelope."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class AgentWsRegisterMessage(BaseModel):
    """Shared websocket registration from one Unity app connection."""

    model_config = ConfigDict(extra="allow")

    type: Literal["register"] = "register"
    creature_ids: list[str] = Field(default_factory=list)

    @field_validator("creature_ids", mode="before")
    @classmethod
    def _coerce_creature_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        return []

    @field_validator("creature_ids")
    @classmethod
    def _clean_creature_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned


class AgentWsTickEnvelope(BaseModel):
    """One per-cat tick carried over the shared app websocket."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["tick"] = "tick"
    agent_id: str = ""
    creature_id: str = ""
    request_id: str = Field("", alias="requestId")
    report: dict[str, Any] | None = None
    snapshot: dict[str, Any]

    @model_validator(mode="after")
    def _fill_ids_from_snapshot(self) -> "AgentWsTickEnvelope":
        if not self.creature_id:
            self.creature_id = self.agent_id
        if not self.creature_id and isinstance(self.snapshot, dict):
            self.creature_id = str(self.snapshot.get("agent_id") or "").strip()
        if not self.agent_id:
            self.agent_id = self.creature_id
        if not self.request_id and isinstance(self.snapshot, dict):
            self.request_id = str(
                self.snapshot.get("requestId") or self.snapshot.get("request_id") or ""
            )
        self.creature_id = self.creature_id.strip()
        self.agent_id = self.agent_id.strip()
        self.request_id = self.request_id.strip()
        return self


class AgentWsRegisteredResponse(BaseModel):
    type: Literal["registered"] = "registered"
    status: Literal["ok"] = "ok"
    creature_ids: list[str] = Field(default_factory=list)
