from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agent.mind.intents import (
    INTENT_EXPLORE,
    INTENT_IDLE,
    INTENT_INVESTIGATE,
    INTENT_REST,
    INTENT_SAFETY,
    INTENT_SEEK_FOOD,
    INTENT_SEEK_PLAYER,
    INTENT_SOCIALIZE,
    normalize_intent,
)
from app.agent.prompts.sections import clean_text, explore_frontier_lines


DEFAULT_AVAILABLE_INTENTS = (
    INTENT_EXPLORE,
    INTENT_INVESTIGATE,
    INTENT_SEEK_FOOD,
    INTENT_SEEK_PLAYER,
    INTENT_SOCIALIZE,
    INTENT_REST,
    INTENT_SAFETY,
    INTENT_IDLE,
)


@dataclass(frozen=True)
class AffordanceTarget:
    id: str
    supports: tuple[str, ...] = ()

    def supports_intent(self, intent: str) -> bool:
        return not self.supports or intent in self.supports

    def to_prompt_line(self) -> str:
        support = ", ".join(self.supports) if self.supports else "any listed intent"
        return f"{self.id}: supports {support}"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "supports": list(self.supports)}


@dataclass(frozen=True)
class IntentAffordances:
    available_intents: tuple[str, ...]
    targets: tuple[AffordanceTarget, ...]

    def allows_intent(self, intent: str) -> bool:
        return intent == INTENT_IDLE or not self.available_intents or intent in self.available_intents

    def target_supports_intent(self, target_id: str, intent: str) -> bool:
        if not target_id or not self.targets:
            return True
        for target in self.targets:
            if target.id == target_id:
                return target.supports_intent(intent)
        return False

    def target_ids(self) -> set[str]:
        return {target.id for target in self.targets}

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "available_intents": list(self.available_intents),
            "targets": [target.to_dict() for target in self.targets],
        }


def build_intent_affordances(
    raw_payload: dict[str, Any] | None,
    *,
    semantic_context: dict[str, Any] | None = None,
    place_memory_context: dict[str, Any] | None = None,
    world_view: dict[str, Any] | None = None,
) -> IntentAffordances:
    """Read Unity's intent affordance contract, with legacy context fallback."""

    raw = raw_payload if isinstance(raw_payload, dict) else {}
    source = _affordance_source(raw)

    available = _normalize_available_intents(source.get("available_intents"))
    if not available:
        available = DEFAULT_AVAILABLE_INTENTS

    targets = _targets_from_contract(source.get("targets"))
    if not targets:
        targets = tuple(_targets_from_context(
            semantic_context=semantic_context,
            place_memory_context=place_memory_context,
            world_view=world_view,
        ))

    return IntentAffordances(
        available_intents=tuple(intent for intent in available if intent != INTENT_IDLE),
        targets=targets,
    )


def format_affordances_for_prompt(affordances: IntentAffordances) -> str:
    intents = ", ".join(affordances.available_intents) or INTENT_IDLE
    lines = [f"available_intents: {intents}"]
    if affordances.targets:
        lines.append("targets:")
        lines.extend(f"  - {target.to_prompt_line()}" for target in affordances.targets)
    else:
        lines.append("targets: none reported")
    return "\n".join(lines)


def _affordance_source(raw: dict[str, Any]) -> dict[str, Any]:
    for key in ("intent_affordances", "affordances", "affordance", "available_affordances"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    return raw


def _normalize_available_intents(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    intents: list[str] = []
    for item in value:
        intent = normalize_intent(item, default="")
        if intent and intent not in intents:
            intents.append(intent)
    return tuple(intents)


def _targets_from_contract(value: Any) -> tuple[AffordanceTarget, ...]:
    if not isinstance(value, list):
        return ()
    targets: list[AffordanceTarget] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target_id = clean_text(item.get("id") or item.get("target_id") or item.get("target"))
        if not target_id:
            continue
        supports = _normalize_available_intents(item.get("supports"))
        targets.append(AffordanceTarget(target_id, supports=supports))
    return tuple(_dedupe_targets(targets))


def _targets_from_context(
    *,
    semantic_context: dict[str, Any] | None,
    place_memory_context: dict[str, Any] | None,
    world_view: dict[str, Any] | None,
) -> list[AffordanceTarget]:
    context = semantic_context if isinstance(semantic_context, dict) else {}
    targets: list[AffordanceTarget] = []
    targets.extend(_targets_from_lines(context.get("food_nearby"), (INTENT_SEEK_FOOD,)))
    targets.extend(_targets_from_lines(context.get("social_cues"), (INTENT_SOCIALIZE, INTENT_INVESTIGATE)))
    targets.extend(_targets_from_lines(context.get("objects_nearby"), (INTENT_INVESTIGATE,)))
    targets.extend(_targets_from_lines(context.get("relevant_targets"), (INTENT_INVESTIGATE,)))
    targets.extend(_targets_from_lines(explore_frontier_lines(place_memory_context), (INTENT_EXPLORE,)))

    if isinstance(world_view, dict):
        peers = world_view.get("peers_in_zone")
        if isinstance(peers, list):
            for peer in peers:
                if isinstance(peer, dict):
                    creature_id = clean_text(peer.get("creature_id"))
                    if creature_id:
                        targets.append(AffordanceTarget(creature_id, (INTENT_SOCIALIZE, INTENT_SEEK_PLAYER)))

    return _dedupe_targets(targets)


_TARGET_ID_PATTERN = re.compile(r"\btarget id\s*:\s*([^.;]+)", re.IGNORECASE)
_TARGET_PATTERN = re.compile(r"\btargets?\s*:\s*([^.;]+)", re.IGNORECASE)


def _targets_from_lines(value: Any, supports: tuple[str, ...]) -> list[AffordanceTarget]:
    lines = value if isinstance(value, list) else [value]
    targets: list[AffordanceTarget] = []
    for line in lines:
        text = clean_text(line)
        if not text:
            continue
        matches = _TARGET_ID_PATTERN.findall(text) or _TARGET_PATTERN.findall(text)
        if not matches:
            continue
        for match in matches:
            raw_ids = match.replace(" and ", ",")
            for target_id in raw_ids.split(","):
                target = clean_text(target_id)
                if target:
                    targets.append(AffordanceTarget(target, supports))
    return targets


def _dedupe_targets(targets: list[AffordanceTarget]) -> list[AffordanceTarget]:
    by_id: dict[str, set[str]] = {}
    order: list[str] = []
    for target in targets:
        if target.id not in by_id:
            by_id[target.id] = set()
            order.append(target.id)
        by_id[target.id].update(target.supports)
    return [
        AffordanceTarget(target_id, tuple(sorted(by_id[target_id])))
        for target_id in order
    ]
