"""
schemas/perception.py — Data types for the perception pipeline.

These are pure data containers.  SnapshotManager (the logic) lives in
perception.py.  This file has no business logic, no imports from other
agent modules.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from pydantic import BaseModel


# ─── Raw from Unity (Pydantic for validation) ───────────────────────────────

class Vector3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class EntityObservation(BaseModel):
    name: str = ""
    tag: str = ""
    position: Vector3 = Vector3()
    distance: float = 0.0


class CreatureSnapshot(BaseModel):
    position: Vector3 = Vector3()
    rotation_y: float = 0.0
    active_state: str = "none"
    active_stance: str = "none"
    grounded: bool = True
    speed: float = 0.0
    sprint: bool = False


class EnvironmentSnapshot(BaseModel):
    time_of_day: float = 12.0
    weather: str = "clear"
    entities: list[EntityObservation] = []


# ─── Agent business logic output ────────────────────────────────────────────

class ThreatLevel(IntEnum):
    SAFE = 0
    CAUTION = 1
    DANGER = 2


@dataclass
class PerceptionSummary:
    """What the agent knows after processing one tick of environment data."""

    creature: CreatureSnapshot
    environment: EnvironmentSnapshot
    nearby_entities: list[EntityObservation] = field(default_factory=list)
    threat_level: ThreatLevel = ThreatLevel.SAFE
    tick: int = 0

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "threat_level": self.threat_level.name.lower(),
            "creature": self.creature.model_dump(),
            "environment": self.environment.model_dump(),
            "nearby_entities": [e.model_dump() for e in self.nearby_entities],
            "entity_count": len(self.nearby_entities),
        }


@dataclass
class PerceptionError:
    message: str
    raw_payload: dict | None = None