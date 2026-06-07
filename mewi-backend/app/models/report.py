"""Models for raw behavioral report session ingestion."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


REPORT_RAW_SCHEMA_VERSION = "mewi.report.raw.v1"


class ReportSource(BaseModel):
    model_config = ConfigDict(extra="allow")

    app: str = "mewi-unity"
    build: str = ""
    platform: str = ""
    scene: str = ""


class ReportEventParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    zone_id: str = ""
    target_id: str = ""
    item_id: str = ""
    subtype: str = ""
    initiated_by: str = ""
    distance_to_player_m: float = -1.0
    distance_to_nearest_cat_m: float = -1.0
    speed_mps: float = -1.0


class ReportEventMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_system: str = ""
    recorder: str = ""
    derivation: str = ""
    note: str = ""


class ReportEventInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    t: float = Field(ge=0.0)
    actor: Literal["human", "cat"]
    action: str = Field(min_length=1)
    cat_id: str = ""
    trust_before: int = Field(0, ge=0, le=100)
    trust_after: int = Field(0, ge=0, le=100)
    trigger: str = ""
    params: ReportEventParams = Field(default_factory=ReportEventParams)
    meta: ReportEventMeta = Field(default_factory=ReportEventMeta)

    @field_validator("cat_id")
    @classmethod
    def _cat_event_requires_cat_id(cls, value: str, info) -> str:
        actor = info.data.get("actor")
        if actor == "cat" and not (value or "").strip():
            raise ValueError("cat events require cat_id")
        return (value or "").strip().lower()

    @field_validator("action", "trigger")
    @classmethod
    def _normalize_snakeish(cls, value: str) -> str:
        return (value or "").strip()


class ReportMultiCatEncounter(BaseModel):
    model_config = ConfigDict(extra="allow")

    t: float = Field(ge=0.0)
    cats_present: list[str] = Field(default_factory=list, min_length=2)
    human_action: str = Field(min_length=1)
    outcome: str = Field(min_length=1)


class ReportSessionInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = Field(min_length=1)
    session_index: int = Field(ge=1)
    timestamp_start: str = Field(min_length=1)
    duration_seconds: float = Field(ge=0.0)
    events: list[ReportEventInput] = Field(default_factory=list)
    multi_cat_encounters: list[ReportMultiCatEncounter] = Field(default_factory=list)

    @field_validator("events")
    @classmethod
    def _events_are_chronological(cls, value: list[ReportEventInput]) -> list[ReportEventInput]:
        times = [event.t for event in value]
        if times != sorted(times):
            raise ValueError("events must be sorted by t ascending")
        return value


class ReportSessionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["mewi.report.raw.v1"] = REPORT_RAW_SCHEMA_VERSION
    user_id: str = Field(min_length=1)
    source: ReportSource = Field(default_factory=ReportSource)
    session: ReportSessionInput

    @field_validator("user_id")
    @classmethod
    def _clean_user_id(cls, value: str) -> str:
        return value.strip()


class ReportSessionAcceptedResponse(BaseModel):
    status: str = "accepted"
    user_id: str
    session_id: str
    stored: bool
    session_count: int
    processing_queued: bool = False
    storage_key: str

