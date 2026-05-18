"""
Unity sensor payload schemas for POST /agent/tick/{creature_id}.

Centralised here so the router, tests, and future tooling all share one
definition.  The `self` JSON key is mapped to the Python attribute
`self_state` via Field(alias="self") to avoid shadowing the built-in.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    hunger: float = Field(0.0, ge=0.0, le=1.0)


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


class TickPayload(BaseModel):
    """
    One environment snapshot pushed from Unity each game tick.

    creature_id is a URL path parameter — not part of the sensor payload.
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


class TickResponse(BaseModel):
    """
    Response returned to Unity after each tick.

    During the aggregation window (buffer not yet full):
      {"status": "buffering", "buffered_count": N, "latency_ms": 4.2}

    On a flush tick (buffer reached 10), the LLM result is populated:
      {"tick": 42, "action": {...}, "reasoning": "...", "latency_ms": 3241.8}

    latency_ms is the total server-side wall time for this tick in milliseconds.
    Unity can use this to calibrate animation timing and polling intervals.
    """
    tick:           int | None            = None
    action:         dict[str, Any] | None = None
    reasoning:      str | None            = None
    status:         str | None            = None  # "buffering" during fill phase
    buffered_count: int | None            = None  # current buffer depth when buffering
    latency_ms:     float | None          = None  # total server wall time (ms)


class AgentStatusResponse(BaseModel):
    """Current backend runtime state for one creature."""
    creature_id: str
    status: str = "idle"
    is_thinking: bool = False


class AgentResultResponse(BaseModel):
    """Latest brain decision published by the background tick pipeline."""
    creature_id: str
    status: str = "pending"  # pending | done | error
    request_id: str = ""
    tick: int | None = None
    action: str = ""
    reasoning: str = ""
    detail: str = ""
    success: bool | None = None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    target: str = ""
    raw: dict[str, Any] | None = None


class ActionReportPayload(BaseModel):
    """Execution status callback posted by Unity after it accepts/runs an intent."""
    model_config = ConfigDict(populate_by_name=True)

    agent_id:   str          = ""
    command_id: str          = Field("", alias="commandId")
    request_id: str          = Field("", alias="requestId")
    action:     str          = ""
    status:     str          = ""
    reason:     str          = ""
    time:       float | None = None


class ActionReportResponse(BaseModel):
    """Acknowledgement for a Unity execution-status callback."""
    status: str = "ok"
    creature_id: str = ""
    stored: bool = False


class ActionReportsResponse(BaseModel):
    """Recent Unity execution reports for one creature."""
    creature_id: str
    reports: list[ActionReportPayload] = Field(default_factory=list)


class RuntimeClearResponse(BaseModel):
    """Runtime cache cleanup response for local/dev reset flows."""
    creature_id: str
    deleted: int = 0
