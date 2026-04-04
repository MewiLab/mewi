import logging

from typing import Any
 
from pydantic import ValidationError
 
from app.agent.schemas.perception import (
    # Raw from unity
    EnvironmentSnapshot,
    EntityObservation,
    CreatureSnapshot,
    # Agent business logic output
    ThreatLevel,
    PerceptionSummary,
    PerceptionError,
)

logger = logging.getLogger(__name__)


class SnapshotManager:
    
    def __init__(
        self,
        relevance_radius: float = 30.0,
        threat_radius: float = 10.0,
        hostile_tags: set[str] | None = None,
    ):
        # game scenarios can tune perception without editing this file.
        self.relevance_radius = relevance_radius
        self.threat_radius = threat_radius
        self.hostile_tags = hostile_tags or {"predator", "hostile", "trap"}
 

        self.tick_count: int = 0
        self.last_summary: PerceptionSummary | None = None

    def process(self, raw_json: dict[str, Any]) -> PerceptionSummary | PerceptionError:
        """
        Main entry point.  Takes the raw dict from Unity's HTTP response
        and returns either a typed summary or a typed error.
 
        Why return a union instead of raising?  Because a bad payload from
        Unity is an expected condition (network glitch, schema mismatch
        during development), not an exceptional one.  The caller decides
        how to handle it — retry, log, fall back to last known state.
        """
 
        parsed = self._validate(raw_json)
        if isinstance(parsed, PerceptionError):
            return parsed
 
        env_data, creature_data = parsed
 
        all_entities = env_data.entities if hasattr(env_data, "entities") else []
        nearby = self._filter_by_relevance(all_entities, creature_data)
 
        threat = self._assess_threat(nearby, creature_data)
 
        self.tick_count += 1
        summary = PerceptionSummary(
            creature=creature_data,
            environment=env_data,
            nearby_entities=nearby,
            threat_level=threat,
            tick=self.tick_count,
        )
 
        self.last_summary = summary
        return summary
 
    def get_last_summary(self) -> PerceptionSummary | None:
        """Returns the most recent successful perception, or None if
        process() has never been called or always failed."""
        return self.last_summary
 
    def _validate(
        self, raw_json: dict[str, Any]
    ) -> tuple[EnvironmentSnapshot, CreatureSnapshot] | PerceptionError:
        try:
            env_data = EnvironmentSnapshot(
                **raw_json.get("environment_snapshot", {})
            )
            creature_data = CreatureSnapshot(
                **raw_json.get("creature_snapshot", {})
            )
            return env_data, creature_data
 
        except ValidationError as e:
            logger.warning("Payload validation failed: %s", e.error_count())
            logger.debug("Validation details: %s", e.errors())
            return PerceptionError(
                message=f"Schema validation failed ({e.error_count()} errors)",
                raw_payload=raw_json,
            )
 
    def _filter_by_relevance(
        self,
        entities: list[EntityObservation],
        creature: CreatureSnapshot,
    ) -> list[EntityObservation]:
        """
        Drop entities too far away to matter.
 
        Why distance-based instead of a fixed list?  The relevance radius
        is tunable per-scenario — a cat in an open field needs a wider
        radius than one indoors.  And it's the simplest filter that
        actually reduces noise for the LLM.
        """
        if not entities:
            return []
 
        creature_pos = getattr(creature, "position", None)
        if creature_pos is None:
            return entities  # Can't filter without position, return all.
 
        return [
            e
            for e in entities
            if self._distance(creature_pos, e.position) <= self.relevance_radius
        ]
 
    def _assess_threat(
        self,
        nearby_entities: list[EntityObservation],
        creature: CreatureSnapshot,
    ) -> ThreatLevel:
        """
        Classify the current danger level from nearby entities.
        """
        if not nearby_entities:
            return ThreatLevel.SAFE
 
        creature_pos = getattr(creature, "position", None)
 
        for entity in nearby_entities:
            tag = getattr(entity, "tag", "").lower()
            if tag not in self.hostile_tags:
                continue
 
            if creature_pos is not None:
                dist = self._distance(creature_pos, entity.position)
                if dist <= self.threat_radius:
                    return ThreatLevel.DANGER
 
            return ThreatLevel.CAUTION
 
        return ThreatLevel.SAFE
 
    @staticmethod
    def _distance(a, b) -> float:
        return (
            (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2
        ) ** 0.5