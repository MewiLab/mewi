"""
SemanticService - X-to-1 compression for Unity perception snapshots.

Condenses a buffer of raw Unity JSON payloads into a compact, human-readable
paragraph suitable for long-term storage and LLM retrieval. The Unity payload is
channel based, so this service keeps each channel formatter small and explicit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.logger import get_logger
from app.services.perception.text_signals import recently_ate


def _format_previous_action_result(value: Any) -> str:
    # Lazy import: app.agent.mind.context lives behind a package whose __init__
    # transitively imports SemanticService, so a top-level import would cycle.
    from app.agent.mind.context import format_previous_action_result
    return format_previous_action_result(value)

if TYPE_CHECKING:
    from app.services.perception.embedding_service import EmbeddingService

logger = get_logger(__name__)

Snapshot = dict[str, Any]


@dataclass(frozen=True)
class MetricSpec:
    """One numeric field worth describing and tracking across a window."""

    channel: str
    key: str
    label: str
    default: float
    low_word: str = ""
    moderate_word: str = ""
    high_word: str = ""

    def word_for(self, band: str) -> str:
        return {
            "low": self.low_word,
            "moderate": self.moderate_word,
            "high": self.high_word,
        }.get(band, "")


@dataclass(frozen=True)
class FeelingChannelSpec:
    """A compact list field emitted by Unity's FeelingsChannel."""

    key: str
    verb: str
    limit: int


MOOD_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("mood", "fear", "Fear", 0.0, moderate_word="uneasy", high_word="fearful"),
    MetricSpec("mood", "trust", "Trust", 0.0, moderate_word="open", high_word="trusting"),
    MetricSpec("mood", "curiosity", "Curiosity", 0.5, high_word="curious"),
    MetricSpec("mood", "social", "Social", 0.0, moderate_word="engaged", high_word="social"),
    MetricSpec("mood", "energy", "Energy", 1.0, low_word="tired"),
)

HEALTH_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("health", "fullness", "Fullness", 1.0),
)

FEELING_CHANNELS: tuple[FeelingChannelSpec, ...] = (
    FeelingChannelSpec("smells", "smelled", 4),
    FeelingChannelSpec("sounds", "heard", 4),
    FeelingChannelSpec("signals", "detected", 6),
)

MAX_OBSERVATIONS = 8

FOOD_TERMS = {
    "fish",
    "food",
    "edible",
    "eat",
    "meal",
    "treat",
    "meat",
    "milk",
}
SOCIAL_TERMS = {
    "cat",
    "kitten",
    "player",
    "human",
    "person",
    "child",
}
DANGER_TERMS = {
    "danger",
    "unsafe",
    "threat",
    "sharp",
    "fire",
    "flame",
    "hot",
    "sudden",
    "loud",
}

DIRECTION_PHRASES = {
    "front": "ahead",
    "front_left": "ahead-left",
    "left": "to the left",
    "back_left": "behind-left",
    "back": "behind",
    "back_right": "behind-right",
    "right": "to the right",
    "front_right": "ahead-right",
    "all_around": "all around",
    "contact": "in contact",
    "above": "above",
    "below": "below",
}

CONFINEMENT_PHRASES = {
    "semi": "partly sheltered",
    "confined": "enclosed",
    "open": "open",
}


class SemanticService:
    """Convert a list of raw Unity snapshots into one narrative paragraph."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._embedding = embedding_service

    # -- Generic helpers -----------------------------------------------------

    @staticmethod
    def _label(value: float) -> str:
        """Map a [0, 1] float to a categorical intensity word."""
        if value < 0.3:
            return "low"
        if value <= 0.7:
            return "moderate"
        return "high"

    @staticmethod
    def _natural_join(items: list[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return ", ".join(items[:-1]) + ", and " + items[-1]

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())

    @classmethod
    def _as_text_list(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [text] if (text := cls._clean_text(value)) else []
        if not isinstance(value, (list, tuple, set)):
            return []
        return [text for item in value if (text := cls._clean_text(item))]

    @staticmethod
    def _as_dicts(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _section(snapshot: Snapshot, key: str) -> dict[str, Any]:
        value = snapshot.get(key)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _ensure_sentence(text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        return text if text[-1] in ".!?" else f"{text}."

    @staticmethod
    def _capitalize_first(text: str) -> str:
        return f"{text[:1].upper()}{text[1:]}" if text else text

    def _metric_value(self, snapshot: Snapshot, spec: MetricSpec) -> float:
        section = self._section(snapshot, spec.channel)
        if spec.channel == "health" and spec.key == "fullness":
            if "fullness" in section:
                return self._safe_float(section.get("fullness"), spec.default)
            if "hunger" in section:
                hunger = self._safe_float(section.get("hunger"), 0.0)
                return 1.0 - max(0.0, min(1.0, hunger))
        return self._safe_float(section.get(spec.key, spec.default), spec.default)

    # -- Channel formatters --------------------------------------------------

    def _current_action(self, snapshot: Snapshot) -> str:
        return self._clean_text(self._section(snapshot, "self").get("current_action")) or "resting"

    def _describe_mood(self, mood_data: dict[str, Any]) -> str:
        words: list[str] = []
        mood = mood_data if isinstance(mood_data, dict) else {}
        for spec in MOOD_METRICS:
            value = self._safe_float(mood.get(spec.key, spec.default), spec.default)
            word = spec.word_for(self._label(value))
            if word:
                words.append(word)
        return self._natural_join(words) if words else "calm"

    def _format_mood_and_health(self, last: Snapshot) -> str:
        mood_str = self._describe_mood(self._section(last, "mood"))
        fullness_spec = HEALTH_METRICS[0]
        fullness = self._metric_value(last, fullness_spec)
        return f"It felt {mood_str}; fullness was {self._label(fullness)}."

    def _format_feelings(self, snapshots: list[Snapshot]) -> list[str]:
        summary = self._latest_feeling_summary(snapshots)
        clauses: list[str] = []

        for spec in FEELING_CHANNELS:
            values = self._collect_feeling_values(snapshots, spec.key, spec.limit)
            if values:
                clauses.append(f"{spec.verb} {self._natural_join(values)}")

        for key in self._unknown_feeling_keys(snapshots):
            values = self._collect_feeling_values(snapshots, key, limit=3)
            label = key.replace("_", " ")
            if values:
                clauses.append(f"sensed {label}: {self._natural_join(values)}")

        sentences: list[str] = []
        if summary:
            sentences.append(self._ensure_sentence(self._capitalize_first(summary)))
        if clauses:
            subject = "It also" if summary else "It"
            sentences.append(f"{subject} {self._natural_join(clauses)}.")
        return sentences

    def _latest_feeling_summary(self, snapshots: list[Snapshot]) -> str:
        for snapshot in reversed(snapshots):
            feelings = self._section(snapshot, "feelings")
            summary = self._clean_text(feelings.get("summary"))
            if summary:
                return summary
        return ""

    def _collect_feeling_values(self, snapshots: list[Snapshot], key: str, limit: int) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for snapshot in reversed(snapshots):
            feelings = self._section(snapshot, "feelings")
            for value in self._as_text_list(feelings.get(key)):
                dedupe_key = value.lower()
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    values.append(value)
                if len(values) >= limit:
                    return values
        return values

    def _unknown_feeling_keys(self, snapshots: list[Snapshot]) -> list[str]:
        known = {"summary", *(spec.key for spec in FEELING_CHANNELS)}
        keys: list[str] = []
        seen: set[str] = set()
        for snapshot in reversed(snapshots):
            feelings = self._section(snapshot, "feelings")
            for key, value in feelings.items():
                if key in known or key in seen or not self._as_text_list(value):
                    continue
                seen.add(key)
                keys.append(key)
        return keys

    def _format_spatial_context(self, last: Snapshot) -> str:
        location = self._snapshot_location_text(last)
        zones = self._zone_phrases(last)

        if location and zones:
            return f"It was at {location}, within {self._natural_join(zones)}."
        if location:
            return f"It was at {location}."
        if zones:
            return f"It was within {self._natural_join(zones)}."
        return ""

    def _snapshot_location_text(self, snapshot: Snapshot) -> str:
        self_state = self._section(snapshot, "self")
        location = self_state.get("location") or self_state.get("location_label")
        if isinstance(location, dict):
            x = self._safe_float(location.get("x"), 0.0)
            y = self._safe_float(location.get("y"), 0.0)
            z = self._safe_float(location.get("z"), 0.0)
            return f"({x:.1f},{y:.1f},{z:.1f})"
        return self._clean_text(location)

    def _zone_phrases(self, snapshot: Snapshot) -> list[str]:
        spatial = self._section(snapshot, "spatial_context")
        zones: list[str] = []
        seen: set[str] = set()
        for zone in self._as_dicts(spatial.get("zones")):
            zone_id = self._clean_text(zone.get("id"))
            zone_type = self._clean_text(zone.get("type"))
            label = zone_id or zone_type
            if not label:
                continue

            details = [
                detail
                for detail in (
                    zone_type if zone_type and zone_type.lower() != label.lower() else "",
                    self._clean_text(zone.get("confinement")),
                    self._clean_text(zone.get("surface")),
                )
                if detail
            ]
            phrase = f"{label} ({', '.join(details)})" if details else label
            dedupe_key = phrase.lower()
            if dedupe_key not in seen:
                seen.add(dedupe_key)
                zones.append(phrase)
        return zones

    def _collect_observations(self, snapshots: list[Snapshot]) -> list[str]:
        observations_by_key: dict[str, str] = {}
        ordered_keys: list[str] = []

        for snapshot in snapshots:
            for entity in self._as_dicts(snapshot.get("entities")):
                entity_key = self._entity_observation_key(entity)
                observation = self._format_entity_observation(entity)
                if not entity_key or not observation:
                    continue
                if entity_key not in observations_by_key:
                    ordered_keys.append(entity_key)
                observations_by_key[entity_key] = observation

        return [observations_by_key[key] for key in ordered_keys[:MAX_OBSERVATIONS]]

    def _entity_observation_key(self, entity: dict[str, Any]) -> str:
        entity_id = self._clean_text(entity.get("id"))
        if entity_id:
            return f"id:{entity_id.lower()}"

        tags = self._as_text_list(entity.get("tags"))
        if tags:
            return "tags:" + "|".join(tag.lower() for tag in tags)

        return ""

    def _format_entity_observation(self, entity: dict[str, Any]) -> str:
        tags = self._as_text_list(entity.get("tags"))
        entity_id = self._clean_text(entity.get("id"))
        label = self._natural_join(tags[:3]) if tags else entity_id
        if not label:
            return ""

        context: list[str] = []
        if entity_id and entity_id != label:
            context.append(entity_id)

        direction = self._clean_text(entity.get("direction"))
        if direction:
            context.append(direction)

        if "distance" in entity:
            distance = self._safe_float(entity.get("distance"), default=math.nan)
            if math.isfinite(distance):
                context.append(f"{distance:.1f}m")

        return f"{label} ({', '.join(context)})" if context else label

    def _format_trends(self, snapshots: list[Snapshot]) -> str:
        if len(snapshots) < 2:
            return ""

        first = snapshots[0]
        last = snapshots[-1]
        trends: list[str] = []

        first_action = self._current_action(first)
        last_action = self._current_action(last)
        if first_action != last_action:
            trends.append(f"Action changed from {first_action} to {last_action}")

        first_location = self._snapshot_location_text(first)
        last_location = self._snapshot_location_text(last)
        if first_location and last_location and first_location != last_location:
            trends.append(f"Location changed from {first_location} to {last_location}")

        for spec in (*MOOD_METRICS, *HEALTH_METRICS):
            trend = self._trend(
                spec.label,
                self._metric_value(first, spec),
                self._metric_value(last, spec),
            )
            if trend:
                trends.append(trend)

        return f"Over this window: {'; '.join(trends)}." if trends else ""

    def _trend(self, label: str, start: float, end: float) -> str | None:
        """
        Return a trend phrase when the intensity category changed between
        the first and last snapshot. Returns None when stable.
        """
        s, e = self._label(start), self._label(end)
        if s == e:
            return None
        return f"{label} went from {s} to {e}"

    # -- Live prompt context -------------------------------------------------

    def build_prompt_context(self, snapshot: Snapshot) -> dict[str, Any]:
        """
        Translate one live Unity snapshot into high-level prompt sections.

        This is intentionally different from generate_summary(): summaries are
        narrative memory records, while prompt context is decision support. It
        should hide raw Unity telemetry and expose only behavioral meaning plus
        exact target ids where Unity actions need them.
        """
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        targets = self._semantic_targets(snapshot)
        sensory = self._semantic_sensory_lines(snapshot)
        typed = self._semantic_typed_targets(snapshot)

        return {
            # Legacy keys — still consumed by the strategic-commander prompt
            # and a handful of tests. New prompts use the typed blocks below.
            "situation": self._semantic_situation(snapshot),
            "body_state": self._semantic_body_state(snapshot),
            "sensory_world": sensory,
            "relevant_targets": targets or ["No meaningful nearby target is currently visible."],
            "decision_focus": self._semantic_decision_focus(snapshot, targets, sensory),
            # New typed blocks — keep each list short, with empty lists for
            # missing sections so the prompt formatter can decide whether to
            # render or skip a heading.
            "body_lines": self._semantic_body_lines(snapshot),
            "food_nearby": typed["food_nearby"],
            "social_cues": typed["social_cues"],
            "objects_nearby": typed["objects_nearby"],
            "whats_changed": self._semantic_whats_changed(snapshot),
        }

    def _semantic_situation(self, snapshot: Snapshot) -> str:
        action = self._current_action(snapshot)
        place = self._semantic_place(snapshot)
        if place:
            return f"The cat is {action} {place}."
        return f"The cat is {action} in an unspecified place."

    def _semantic_place(self, snapshot: Snapshot) -> str:
        self_state = self._section(snapshot, "self")
        location = self._display_name(self_state.get("location") or self_state.get("location_label"))
        zones = self._as_dicts(self._section(snapshot, "spatial_context").get("zones"))
        if not zones:
            return f"at {location}" if location else ""

        broad = self._display_name(zones[0].get("id")) if zones else ""
        current = zones[-1]
        current_name = self._display_name(current.get("id")) or location
        place_kind = self._place_kind(current)

        if current_name and broad and current_name.lower() != broad.lower():
            return f"on {current_name}, {place_kind} within {broad}"
        if current_name:
            return f"on {current_name}, {place_kind}"
        if broad:
            return f"in {broad}"
        return ""

    def _place_kind(self, zone: dict[str, Any]) -> str:
        parts: list[str] = []
        confinement = self._clean_text(zone.get("confinement")).lower()
        if confinement in CONFINEMENT_PHRASES:
            parts.append(CONFINEMENT_PHRASES[confinement])

        surface = self._display_name(zone.get("surface")).lower()
        if surface:
            parts.append("wooden" if surface == "wood" else f"{surface} surface")

        zone_type = self._display_name(zone.get("type")).lower()
        if zone_type:
            parts.append(zone_type)

        return " ".join(parts) if parts else "a known place"

    def _semantic_body_state(self, snapshot: Snapshot) -> str:
        fullness = self._metric_value(snapshot, HEALTH_METRICS[0])
        fear = self._metric_value(snapshot, MOOD_METRICS[0])
        trust = self._metric_value(snapshot, MOOD_METRICS[1])
        curiosity = self._metric_value(snapshot, MOOD_METRICS[2])
        social = self._metric_value(snapshot, MOOD_METRICS[3])
        energy = self._metric_value(snapshot, MOOD_METRICS[4])

        action_text = _format_previous_action_result(snapshot.get("action_result"))

        parts = [
            self._fullness_meaning(fullness, action_text),
            self._fear_meaning(fear),
            self._curiosity_meaning(curiosity),
            self._social_meaning(trust, social),
            self._energy_meaning(energy),
        ]
        return self._ensure_sentence(self._natural_join([part for part in parts if part]))

    def _fullness_meaning(self, value: float, action_text: str = "") -> str:
        """Render the food drive as what the cat experiences: fullness."""
        if recently_ate(action_text):
            return "fullness is at the top — she just took a bite, food is not pressing"
        fullness = max(0.0, min(1.0, value))
        if fullness >= 0.7:
            return "fullness is high — food is not pressing"
        if fullness >= 0.3:
            return "fullness is moderate — food matters but is not desperate"
        return "fullness is low — food is urgent"

    def _semantic_body_lines(self, snapshot: Snapshot) -> list[str]:
        """One short line per drive — easier for the model to weigh than a
        comma-spaghetti sentence. Order matches the original phrasing."""
        fullness = self._metric_value(snapshot, HEALTH_METRICS[0])
        fear = self._metric_value(snapshot, MOOD_METRICS[0])
        trust = self._metric_value(snapshot, MOOD_METRICS[1])
        curiosity = self._metric_value(snapshot, MOOD_METRICS[2])
        social = self._metric_value(snapshot, MOOD_METRICS[3])
        energy = self._metric_value(snapshot, MOOD_METRICS[4])

        action_text = _format_previous_action_result(snapshot.get("action_result"))
        return [
            f"fullness: {self._fullness_meaning(fullness, action_text)}",
            f"fear: {self._fear_meaning(fear)}",
            f"curiosity: {self._curiosity_meaning(curiosity)}",
            f"social: {self._social_meaning(trust, social)}",
            f"energy: {self._energy_meaning(energy)}",
        ]

    def _semantic_typed_targets(self, snapshot: Snapshot) -> dict[str, list[str]]:
        """Split visible entities into FOOD / SOCIAL / OTHER buckets so the
        prompt can show typed need-blocks instead of one mixed list."""
        food: list[str] = []
        social: list[str] = []
        other: list[str] = []
        agent_id = self._clean_text(snapshot.get("agent_id")).lower()

        groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._collect_contract_target_groups(snapshot, groups)
        for entity in self._as_dicts(snapshot.get("entities")):
            if self._is_self_entity(entity, agent_id):
                continue
            target_id = self._clean_text(entity.get("id"))
            label = self._entity_label(entity)
            if not label:
                continue
            bucket = self._entity_bucket(entity, label)
            direction = self._direction_phrase(entity.get("direction"))
            nearness = self._nearness_phrase(entity.get("distance"))
            key = (bucket, label, direction, nearness)
            group = groups.setdefault(key, {
                "bucket": bucket,
                "label": label,
                "direction": direction,
                "nearness": nearness,
                "ids": [],
            })
            if target_id and target_id not in group["ids"]:
                group["ids"].append(target_id)

        for group in groups.values():
            line = self._format_target_line(group)
            if not line:
                continue
            if group["bucket"] == "food":
                food.append(line)
            elif group["bucket"] == "social":
                social.append(line)
            else:
                other.append(line)

        return {
            "food_nearby": food[:MAX_OBSERVATIONS],
            "social_cues": social[:MAX_OBSERVATIONS],
            "objects_nearby": other[:MAX_OBSERVATIONS],
        }

    def _collect_contract_target_groups(
        self,
        snapshot: Snapshot,
        groups: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> None:
        source = self._affordance_source(snapshot)
        for item in self._as_dicts(source.get("targets")):
            target_id = self._clean_text(item.get("id") or item.get("target_id") or item.get("target"))
            if not target_id:
                continue
            tags = self._as_text_list(item.get("tags"))
            label = self._target_label_from_contract(target_id, tags)
            bucket = self._contract_target_bucket(target_id, tags, item)
            key = (bucket, label, "", "")
            group = groups.setdefault(key, {
                "bucket": bucket,
                "label": label,
                "direction": "",
                "nearness": "",
                "ids": [],
            })
            if target_id not in group["ids"]:
                group["ids"].append(target_id)

    def _affordance_source(self, snapshot: Snapshot) -> dict[str, Any]:
        for key in ("intent_affordances", "affordances", "affordance", "available_affordances"):
            value = snapshot.get(key)
            if isinstance(value, dict):
                return value
        return snapshot

    def _target_label_from_contract(self, target_id: str, tags: list[str]) -> str:
        labels = [self._tag_label(tag) for tag in tags]
        labels = [label for label in labels if label]
        if labels:
            return self._natural_join(labels[:2])
        return self._display_name(target_id)

    def _contract_target_bucket(
        self,
        target_id: str,
        tags: list[str],
        item: dict[str, Any],
    ) -> str:
        supports = " ".join(self._as_text_list(item.get("supports"))).lower()
        action = self._clean_text(item.get("action")).lower()
        text = " ".join([target_id, action, supports, *tags]).lower()
        if "seek_food" in supports or self._contains_any(text, FOOD_TERMS):
            return "food"
        if (
            "socialize" in supports
            or "seek_player" in supports
            or self._contains_any(text, SOCIAL_TERMS)
        ):
            return "social"
        return "other"

    def _entity_bucket(self, entity: dict[str, Any], label: str) -> str:
        tag_text = " ".join(self._as_text_list(entity.get("tags"))).lower()
        label_lower = label.lower()
        if self._contains_any(tag_text, FOOD_TERMS) or self._contains_any(label_lower, FOOD_TERMS):
            return "food"
        if self._contains_any(tag_text, SOCIAL_TERMS) or self._contains_any(label_lower, SOCIAL_TERMS):
            return "social"
        return "other"

    def _format_target_line(self, group: dict[str, Any]) -> str:
        label = group["label"]
        ids = group["ids"]
        count_prefix = self._count_prefix(len(ids), label)
        relation = self._natural_join([item for item in [group["nearness"], group["direction"]] if item])
        target_text = self._target_text(ids)
        if relation and target_text:
            return f"{count_prefix} {relation}; {target_text}."
        if target_text:
            return f"{count_prefix}; {target_text}."
        return f"{count_prefix}."

    def _semantic_whats_changed(self, snapshot: Snapshot) -> list[str]:
        """Surface signals that 'something happened since last tick' so the
        model doesn't have to compute the diff. Today: just_ate + just_drank.
        Place-change and new-affordance diffs can layer on later once Unity
        exposes per-tick deltas."""
        action_text = _format_previous_action_result(snapshot.get("action_result"))
        lines: list[str] = []
        if recently_ate(action_text):
            lines.append("she just took a bite — fullness rose")
        from app.services.perception.text_signals import recently_drank, recently_fled, recently_failed_to_reach
        if recently_drank(action_text):
            lines.append("she just drank")
        if recently_fled(action_text):
            lines.append("she just fled from something")
        if recently_failed_to_reach(action_text):
            lines.append("she just failed to reach a target — try a smaller step")
        return lines

    def _fear_meaning(self, value: float) -> str:
        if value >= 0.7:
            return "safety should come first"
        if value >= 0.3:
            return "the cat is cautious"
        return "there is no strong fear signal"

    def _curiosity_meaning(self, value: float) -> str:
        if value >= 0.7:
            return "curiosity is pulling attention outward"
        if value >= 0.3:
            return "curiosity is available for a small inspection"
        return "curiosity is quiet"

    def _social_meaning(self, trust: float, social: float) -> str:
        if trust >= 0.7 or social >= 0.7:
            return "social contact feels welcome"
        if trust >= 0.3 or social >= 0.3:
            return "social contact is possible but should stay gentle"
        return "social contact is not the main draw"

    def _energy_meaning(self, value: float) -> str:
        if value <= 0.3:
            return "energy is low, so rest or stillness fits"
        if value <= 0.7:
            return "energy supports light movement"
        return "energy supports active movement"

    def _semantic_sensory_lines(self, snapshot: Snapshot) -> list[str]:
        feelings = self._section(snapshot, "feelings")
        lines: list[str] = []

        summary = self._clean_text(feelings.get("summary"))
        if summary:
            lines.append(self._ensure_sentence(self._capitalize_first(summary)))

        for key, label in [
            ("smells", "Smell"),
            ("sounds", "Sound"),
            ("signals", "Body signal"),
        ]:
            for value in self._as_text_list(feelings.get(key))[:3]:
                meaning = self._meaningful_feeling(value)
                if meaning:
                    lines.append(f"{label}: {meaning}.")

        return lines or ["No distinct smell, sound, or body-contact cue is reported right now."]

    def _meaningful_feeling(self, value: str) -> str:
        text = self._clean_text(value)
        if not text:
            return ""

        if ":" in text:
            _prefix, text = text.split(":", 1)
            text = text.strip()

        text = text.replace("_", "-")
        return self._ensure_sentence(text).rstrip(".")

    def _semantic_targets(self, snapshot: Snapshot) -> list[str]:
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        agent_id = self._clean_text(snapshot.get("agent_id")).lower()
        self._collect_contract_relevant_groups(snapshot, groups)

        for entity in self._as_dicts(snapshot.get("entities")):
            if self._is_self_entity(entity, agent_id):
                continue

            target_id = self._clean_text(entity.get("id"))
            label = self._entity_label(entity)
            if not label:
                continue

            direction = self._direction_phrase(entity.get("direction"))
            nearness = self._nearness_phrase(entity.get("distance"))
            key = (label, direction, nearness)
            group = groups.setdefault(key, {"label": label, "direction": direction, "nearness": nearness, "ids": []})
            if target_id and target_id not in group["ids"]:
                group["ids"].append(target_id)

        lines: list[str] = []
        for group in groups.values():
            label = group["label"]
            ids = group["ids"]
            count_prefix = self._count_prefix(len(ids), label)
            relation = self._natural_join([item for item in [group["nearness"], group["direction"]] if item])
            target_text = self._target_text(ids)
            if relation and target_text:
                lines.append(f"{count_prefix} {relation}; {target_text}.")
            elif target_text:
                lines.append(f"{count_prefix}; {target_text}.")
            else:
                lines.append(f"{count_prefix}.")

        return lines[:MAX_OBSERVATIONS]

    def _collect_contract_relevant_groups(
        self,
        snapshot: Snapshot,
        groups: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        source = self._affordance_source(snapshot)
        for item in self._as_dicts(source.get("targets")):
            target_id = self._clean_text(item.get("id") or item.get("target_id") or item.get("target"))
            if not target_id:
                continue
            tags = self._as_text_list(item.get("tags"))
            label = self._target_label_from_contract(target_id, tags)
            key = (label, "", "")
            group = groups.setdefault(key, {"label": label, "direction": "", "nearness": "", "ids": []})
            if target_id not in group["ids"]:
                group["ids"].append(target_id)

    def _is_self_entity(self, entity: dict[str, Any], agent_id: str) -> bool:
        entity_id = self._clean_text(entity.get("id")).lower()
        tags = {tag.lower() for tag in self._as_text_list(entity.get("tags"))}
        if not entity_id:
            return False
        if agent_id and entity_id == agent_id:
            return True
        return entity_id in {"cat", "mew", "mewi"} and not tags

    def _entity_label(self, entity: dict[str, Any]) -> str:
        tags = self._as_text_list(entity.get("tags"))
        labels = [self._tag_label(tag) for tag in tags]
        labels = [label for label in labels if label]
        if labels:
            return self._natural_join(labels[:2])
        return self._display_name(entity.get("id"))

    def _tag_label(self, tag: str) -> str:
        raw = self._clean_text(tag)
        if not raw:
            return ""
        leaf = raw.split(".")[-1]
        label = self._display_name(leaf).lower()
        if label == "fish":
            return "fish or food"
        return label

    def _direction_phrase(self, value: Any) -> str:
        key = self._clean_text(value).lower()
        return DIRECTION_PHRASES.get(key, key.replace("_", "-"))

    def _nearness_phrase(self, value: Any) -> str:
        distance = self._safe_float(value, default=math.nan)
        if not math.isfinite(distance):
            return ""
        if distance <= 1.8:
            return "within easy reach"
        if distance <= 4.5:
            return "nearby"
        if distance <= 8.0:
            return "a short walk away"
        return "farther away"

    def _count_prefix(self, count: int, label: str) -> str:
        if count <= 1:
            article = "an" if label[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
            return f"{article} {label}"
        return f"{count} {self._pluralize(label)}"

    @staticmethod
    def _pluralize(label: str) -> str:
        if label == "fish or food":
            return "fish or food cues"
        if label.endswith("s"):
            return label
        return f"{label}s"

    def _target_text(self, ids: list[str]) -> str:
        ids = ids[:4]
        if not ids:
            return ""
        noun = "target" if len(ids) == 1 else "targets"
        return f"{noun}: {self._natural_join(ids)}"

    def _semantic_decision_focus(
        self,
        snapshot: Snapshot,
        targets: list[str],
        sensory_lines: list[str],
    ) -> list[str]:
        mood = self._section(snapshot, "mood")
        fullness = self._metric_value(snapshot, HEALTH_METRICS[0])
        fear = self._safe_float(mood.get("fear", 0.0), 0.0)
        energy = self._safe_float(mood.get("energy", 1.0), 1.0)
        sensory_text = " ".join(sensory_lines).lower()
        target_text = " ".join(targets).lower()

        focus: list[str] = []
        if self._contains_any(sensory_text, DANGER_TERMS) or fear >= 0.7:
            focus.append("Prioritize safety: create distance, stop, or alert before investigating.")
        elif fear <= 0.3:
            focus.append("No clear danger is present, so fleeing is unnecessary unless a new threat appears.")

        food_cue = self._contains_any(sensory_text, FOOD_TERMS) or self._contains_any(target_text, FOOD_TERMS)
        ate_recently = recently_ate(_format_previous_action_result(snapshot.get("action_result")))
        if ate_recently:
            focus.append("She just took a bite — fullness is at the top; consider exploring, resting, or socializing.")
        elif fullness <= 0.3 and food_cue:
            focus.append("Fullness is low and there is an edible cue, so smelling or eating is well motivated.")
        elif fullness <= 0.3:
            focus.append("Fullness is low, but no definite food cue is visible; use smell or a small search before eating.")

        if energy <= 0.3:
            focus.append("Keep the next plan low effort.")

        if not targets:
            focus.append("With no meaningful target, choose a self-directed action such as smelling, waiting, resting, or moving gently.")

        return focus or ["Choose one small, physical action that fits the place and body state."]

    @staticmethod
    def _contains_any(text: str, terms: set[str]) -> bool:
        return any(
            re.search(rf"(^|[._\-\s]){re.escape(term)}($|[._\-\s])", text)
            for term in terms
        )

    def _display_name(self, value: Any) -> str:
        text = self._clean_text(value)
        if not text:
            return ""
        if text.startswith("SM_"):
            text = text[3:]
        return text.replace("_", " ")

    # -- Public API ----------------------------------------------------------

    def generate_summary(
        self,
        snapshots: list[Snapshot],
        location: dict[str, float] | str | None = None,
        timestamp: str | None = None,
    ) -> str:
        """
        Aggregate N Unity snapshots into one narrative paragraph.

        Optionally prepends a spatio-temporal header when `location` is given:
          "[<ISO-timestamp> @ (x, y, z)] The cat was ..."

        Args:
            snapshots: Ordered list of raw Unity payloads (oldest -> newest).
            location: Optional zone string or dict with 'x', 'y', 'z' keys.
            timestamp: Optional ISO-8601 string; defaults to UTC now when location
                       is supplied but timestamp is omitted.
        """
        snapshots = [snapshot for snapshot in snapshots if isinstance(snapshot, dict)]
        if not snapshots:
            return "No perception data available."

        last = snapshots[-1]
        parts: list[str] = [
            f"The cat was {self._current_action(last)}.",
            self._format_mood_and_health(last),
        ]

        parts.extend(self._format_feelings(snapshots))

        spatial_sentence = self._format_spatial_context(last)
        if spatial_sentence:
            parts.append(spatial_sentence)

        trend_sentence = self._format_trends(snapshots)
        if trend_sentence:
            parts.append(trend_sentence)

        observations = self._collect_observations(snapshots)
        if observations:
            parts.append(f"It noticed {self._natural_join(observations)}.")

        body = " ".join(parts)

        if location is not None:
            ts = timestamp or datetime.now(timezone.utc).isoformat()
            if isinstance(location, str):
                label = location.strip() or "unknown zone"
                return f"[{ts} @ {label}] {body}"

            x = self._safe_float(location.get("x"), 0.0)
            y = self._safe_float(location.get("y"), 0.0)
            z = self._safe_float(location.get("z"), 0.0)
            return f"[{ts} @ ({x:.1f},{y:.1f},{z:.1f})] {body}"

        return body

    def generate_embedding(self, text: str) -> list[float]:
        """
        Return an embedding vector for `text`.

        Returns an empty list when no EmbeddingService was injected.
        """
        if self._embedding is None:
            logger.debug("generate_embedding called but no EmbeddingService injected")
            return []
        try:
            return self._embedding.embed_text(text)
        except Exception:
            logger.exception("EmbeddingService.embed_text failed")
            return []
