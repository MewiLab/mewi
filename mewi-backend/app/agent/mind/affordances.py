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
    tags: tuple[str, ...] = ()
    path_status: str = ""
    path_length: float | None = None

    def supports_intent(self, intent: str) -> bool:
        return not self.supports or intent in self.supports

    def to_prompt_line(self) -> str:
        support = ", ".join(self.supports) if self.supports else "any listed intent"
        tag_text = f"; tags {', '.join(self.tags[:4])}" if self.tags else ""
        path = _format_path_status(self.path_status, self.path_length)
        return f"{self.id}: supports {support}{tag_text}{path}"

    def to_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "supports": list(self.supports)}
        if self.tags:
            data["tags"] = list(self.tags)
        if self.path_status:
            data["path_status"] = self.path_status
            data["status"] = self.path_status
        if self.path_status and self.path_length is not None:
            data["path_length"] = self.path_length
        return data


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
            raw_payload=raw,
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
        path_status = clean_text(item.get("path_status") or item.get("status")).lower()
        if path_status == "blocked":
            continue
        tags = _string_tuple(item.get("tags"))
        supports = _normalize_available_intents(item.get("supports"))
        if not supports:
            supports = _supports_from_target(target_id, tags, clean_text(item.get("action")))
        targets.append(AffordanceTarget(
            target_id,
            supports=supports,
            tags=tags,
            path_status=path_status,
            path_length=_optional_float(item.get("path_length")) if path_status else None,
        ))
    return tuple(_dedupe_targets(targets))


def _targets_from_context(
    *,
    raw_payload: dict[str, Any],
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
    targets.extend(_targets_from_reachable_routes(raw_payload))

    if isinstance(world_view, dict):
        peers = world_view.get("peers_in_zone")
        if isinstance(peers, list):
            for peer in peers:
                if isinstance(peer, dict):
                    creature_id = clean_text(peer.get("creature_id"))
                    if creature_id:
                        targets.append(AffordanceTarget(
                            creature_id,
                            (INTENT_SOCIALIZE, INTENT_SEEK_PLAYER),
                            ("social",),
                        ))

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


def _targets_from_reachable_routes(raw_payload: dict[str, Any]) -> list[AffordanceTarget]:
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    place = raw.get("place_context") if isinstance(raw.get("place_context"), dict) else {}
    navigation = raw.get("navigation_context") if isinstance(raw.get("navigation_context"), dict) else {}
    reachable_ids = _string_tuple(place.get("reachable_zone_ids"))
    routes = navigation.get("zone_routes")
    route_status: dict[str, str] = {}
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, dict):
                continue
            route_id = clean_text(route.get("id"))
            if route_id:
                route_status[route_id] = clean_text(route.get("status")).lower()

    candidates = list(reachable_ids) or [
        route_id
        for route_id, status in route_status.items()
        if status and status != "blocked"
    ]

    targets: list[AffordanceTarget] = []
    for zone_id in candidates:
        status = route_status.get(zone_id, "")
        if status == "blocked":
            continue
        tags = ("place", f"route.{status}") if status else ("place",)
        targets.append(AffordanceTarget(zone_id, (INTENT_EXPLORE,), tags, path_status=status))
    return targets


def _dedupe_targets(targets: list[AffordanceTarget]) -> list[AffordanceTarget]:
    by_id: dict[str, set[str]] = {}
    tags_by_id: dict[str, set[str]] = {}
    path_status_by_id: dict[str, str] = {}
    path_length_by_id: dict[str, float | None] = {}
    order: list[str] = []
    for target in targets:
        if target.id not in by_id:
            by_id[target.id] = set()
            tags_by_id[target.id] = set()
            path_status_by_id[target.id] = target.path_status
            path_length_by_id[target.id] = target.path_length
            order.append(target.id)
        by_id[target.id].update(target.supports)
        tags_by_id[target.id].update(target.tags)
        path_status_by_id[target.id] = _best_path_status(
            path_status_by_id[target.id],
            target.path_status,
        )
        path_length_by_id[target.id] = _shorter_path_length(
            path_length_by_id[target.id],
            target.path_length,
        )
    return [
        AffordanceTarget(
            target_id,
            tuple(sorted(by_id[target_id])),
            tuple(sorted(tags_by_id[target_id])),
            path_status_by_id[target_id],
            path_length_by_id[target_id],
        )
        for target_id in order
    ]


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = clean_text(value)
        return (text,) if text else ()
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        text = clean_text(item)
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _optional_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _format_path_status(status: str, path_length: float | None) -> str:
    status = clean_text(status).lower()
    if not status:
        return ""
    if path_length is None:
        return f"; path {status}"
    return f"; path {status}, {path_length:.1f}m"


def _best_path_status(left: str, right: str) -> str:
    return left if _path_rank(left) <= _path_rank(right) else right


def _path_rank(status: str) -> int:
    status = clean_text(status).lower()
    if status == "safe":
        return 0
    if status == "risky":
        return 1
    if status == "blocked":
        return 2
    return 3


def _shorter_path_length(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _supports_from_target(target_id: str, tags: tuple[str, ...], action: str = "") -> tuple[str, ...]:
    text = " ".join((target_id, action, *tags)).lower()
    supports: list[str] = []

    def add(intent: str) -> None:
        if intent not in supports:
            supports.append(intent)

    if _contains_any(text, {"food", "fish", "edible", "eat", "meal", "treat"}):
        add(INTENT_SEEK_FOOD)
        add(INTENT_INVESTIGATE)
    if _contains_any(text, {"player", "human", "person"}):
        add(INTENT_SEEK_PLAYER)
        add(INTENT_SOCIALIZE)
    elif _contains_any(text, {"cat", "kitten", "social"}):
        add(INTENT_SOCIALIZE)
        add(INTENT_INVESTIGATE)
    if _contains_any(text, {"place", "zone", "route", "go_to", "explore"}):
        add(INTENT_EXPLORE)
    if _contains_any(text, {"rest", "sleep", "comfort", "bed", "nest"}):
        add(INTENT_REST)
    if _contains_any(text, {"danger", "unsafe", "threat", "hide", "flee", "safety"}):
        add(INTENT_SAFETY)

    if not supports and (tags or action):
        add(INTENT_INVESTIGATE)
    return tuple(supports)


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(
        re.search(rf"(^|[._\-\s]){re.escape(term)}($|[._\-\s])", text)
        for term in terms
    )
