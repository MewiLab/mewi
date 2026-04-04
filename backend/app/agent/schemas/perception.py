from dataclasses import dataclass, field
from enum import IntEnum

class EnvironmentSnapshot:
    pass

class EntityObservation:
    pass

class CreatureSnapshot:
    pass

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
 
    # Convenience for the LLM context window — a flat dict it can reason about.
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