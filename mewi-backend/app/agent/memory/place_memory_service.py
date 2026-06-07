from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from app.agent.schemas.place_memory_schema import (
    PlaceMemoryContext,
    PlaceMemoryEntry,
    PlaceMemoryOverlay,
)

logger = logging.getLogger(__name__)


class PlaceMemoryStore(Protocol):
    async def record_visit(
        self,
        creature_id: str,
        zone_id: str,
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None: ...

    async def load_overlay(self, creature_id: str) -> PlaceMemoryOverlay: ...

    async def record_seen_places(
        self,
        creature_id: str,
        zone_ids: list[str],
        *,
        observed_at: float,
        request_id: str = "",
    ) -> None: ...


class PlaceMemoryService:
    """Reflects completed movement ticks into prompt-safe place memory."""

    def __init__(self, store: PlaceMemoryStore | None) -> None:
        self._store = store

    async def reflect_tick(
        self,
        creature_id: str,
        snapshot: dict[str, Any],
    ) -> PlaceMemoryContext:
        observation = _extract_place_observation(snapshot)
        current_zone_id = observation["current_zone_id"]
        active_zone_ids = tuple(observation["active_zone_ids"])
        reachable_zone_ids = tuple(observation["reachable_zone_ids"])

        if not current_zone_id:
            return PlaceMemoryContext(
                active_zone_ids=active_zone_ids,
                reachable_zone_ids=reachable_zone_ids,
                lines=("No stable place is reported yet, so exploration memory stays quiet.",),
            )

        if self._store is None:
            return PlaceMemoryContext(
                current_zone_id=current_zone_id,
                active_zone_ids=active_zone_ids,
                reachable_zone_ids=reachable_zone_ids,
                lines=(f"Current place: {_display_name(current_zone_id)}.",),
            )

        observed_at = time.time()
        request_id = _clean_text(snapshot.get("requestId") or snapshot.get("request_id"))

        try:
            if hasattr(self._store, "record_seen_places"):
                await self._store.record_seen_places(
                    creature_id,
                    _known_observation_ids(active_zone_ids, reachable_zone_ids),
                    observed_at=observed_at,
                    request_id=request_id,
                )
            await self._store.record_visit(
                creature_id,
                current_zone_id,
                observed_at=observed_at,
                request_id=request_id,
            )
            overlay = await self._store.load_overlay(creature_id)
        except Exception:
            logger.warning(
                "Place memory unavailable; continuing without coverage creature_id=%s",
                creature_id,
                exc_info=True,
            )
            return PlaceMemoryContext(
                current_zone_id=current_zone_id,
                active_zone_ids=active_zone_ids,
                reachable_zone_ids=reachable_zone_ids,
                lines=(f"Current place: {_display_name(current_zone_id)}.",),
            )

        known_zone_ids = _known_zone_ids(overlay)
        candidate_zone_ids = _candidate_zone_ids(
            reachable_zone_ids,
            overlay,
            active_zone_ids=active_zone_ids,
        )
        best_target = _best_exploration_target(
            candidate_zone_ids,
            overlay,
            observed_at,
            current_zone_id=current_zone_id,
            active_zone_ids=active_zone_ids,
        )
        lines = _build_prompt_lines(
            current_zone_id=current_zone_id,
            reachable_zone_ids=reachable_zone_ids,
            known_zone_ids=known_zone_ids,
            overlay=overlay,
            now=observed_at,
            best_target=best_target,
        )
        return PlaceMemoryContext(
            current_zone_id=current_zone_id,
            active_zone_ids=active_zone_ids,
            reachable_zone_ids=reachable_zone_ids,
            known_zone_ids=known_zone_ids,
            best_exploration_target=best_target,
            lines=tuple(lines),
        )


def _extract_place_observation(snapshot: dict[str, Any]) -> dict[str, Any]:
    place_context = snapshot.get("place_context")
    if not isinstance(place_context, dict):
        place_context = {}

    zones = _zone_ids(snapshot)
    current_zone_id = (
        _clean_text(place_context.get("current_zone_id"))
        or (zones[-1] if zones else "")
    )
    active_zone_ids = _string_list(place_context.get("active_zone_ids")) or zones
    reachable_zone_ids = _string_list(place_context.get("reachable_zone_ids"))

    return {
        "current_zone_id": current_zone_id,
        "active_zone_ids": active_zone_ids,
        "reachable_zone_ids": reachable_zone_ids,
    }


def _zone_ids(snapshot: dict[str, Any]) -> list[str]:
    spatial_context = snapshot.get("spatial_context")
    if not isinstance(spatial_context, dict):
        return []

    zones = spatial_context.get("zones")
    if not isinstance(zones, list):
        return []

    zone_ids: list[str] = []
    seen: set[str] = set()
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        zone_id = _clean_text(zone.get("id"))
        if not zone_id or zone_id.lower() in seen:
            continue
        seen.add(zone_id.lower())
        zone_ids.append(zone_id)
    return zone_ids


def _best_exploration_target(
    candidate_zone_ids: tuple[str, ...],
    overlay: PlaceMemoryOverlay,
    now: float,
    *,
    current_zone_id: str,
    active_zone_ids: tuple[str, ...],
) -> str:
    active = {zone_id.lower() for zone_id in active_zone_ids if zone_id}
    candidates = [
        zone_id
        for zone_id in candidate_zone_ids
        if zone_id
        and zone_id.lower() != current_zone_id.lower()
        and zone_id.lower() not in active
    ]
    if not candidates:
        return ""

    return max(
        candidates,
        key=lambda zone_id: _score_zone(zone_id, overlay, now),
        default="",
    )


def _score_zone(zone_id: str, overlay: PlaceMemoryOverlay, now: float) -> float:
    entry = overlay.get(zone_id)
    if entry is None or entry.visit_count <= 0:
        return 100.0

    seconds_since = max(0.0, now - entry.last_visited_at)
    recency_bonus = min(seconds_since / 60.0, 10.0)
    familiarity_penalty = entry.visit_count * 2.0
    return recency_bonus - familiarity_penalty


def _build_prompt_lines(
    *,
    current_zone_id: str,
    reachable_zone_ids: tuple[str, ...],
    known_zone_ids: tuple[str, ...],
    overlay: PlaceMemoryOverlay,
    now: float,
    best_target: str,
) -> list[str]:
    lines: list[str] = []
    current = overlay.get(current_zone_id)
    current_feel = _familiarity_phrase(current)
    lines.append(f"Current place: {_display_name(current_zone_id)} feels {current_feel}.")

    recent = [
        entry for entry in overlay.recent(limit=5)
        if entry.zone_id.lower() != current_zone_id.lower()
    ][:3]
    if recent:
        recent_text = ", ".join(_display_name(entry.zone_id) for entry in recent)
        lines.append(f"Recently visited: {recent_text}.")

    if known_zone_ids:
        visited_count = sum(
            1 for zone_id in known_zone_ids
            if (entry := overlay.get(zone_id)) is not None and entry.visit_count > 0
        )
        lines.append(
            f"Known places: {len(known_zone_ids)} total; {visited_count} visited by this cat."
        )

    reachable = [
        zone_id
        for zone_id in reachable_zone_ids
        if zone_id and zone_id.lower() != current_zone_id.lower()
    ]
    if reachable:
        unvisited = [
            zone_id for zone_id in reachable
            if (entry := overlay.get(zone_id)) is None or entry.visit_count <= 0
        ]
        if unvisited:
            names = ", ".join(_display_name(zone_id) for zone_id in unvisited[:4])
            lines.append(f"Nearby but not visited yet: {names}.")
        else:
            stale = sorted(
                (overlay.get(zone_id) for zone_id in reachable),
                key=lambda entry: entry.last_visited_at if entry else now,
            )
            stale_names = [
                _display_name(entry.zone_id)
                for entry in stale
                if entry is not None
            ][:3]
            if stale_names:
                lines.append(f"Least recent nearby places: {', '.join(stale_names)}.")

    known_unvisited = [
        zone_id
        for zone_id in known_zone_ids
        if zone_id.lower() != current_zone_id.lower()
        and (entry := overlay.get(zone_id)) is not None
        and entry.visit_count <= 0
    ]
    if known_unvisited:
        names = ", ".join(_display_name(zone_id) for zone_id in known_unvisited[:4])
        lines.append(f"Known but not visited yet: {names}.")

    if best_target:
        lines.append(
            "Best exploration target: "
            f"{_display_name(best_target)}; target id: {best_target}."
        )
    elif not reachable:
        lines.append("No reachable place list is reported yet; explore using visible targets or gentle wandering.")

    lines.append(
        "When fullness is not low and fear is not urgent, curiosity should prefer places that feel new or stale."
    )
    return lines


def _familiarity_phrase(entry: PlaceMemoryEntry | None) -> str:
    if entry is None:
        return "newly noticed"
    if entry.visit_count <= 0:
        return "known but unvisited"
    if entry.visit_count <= 1:
        return "newly visited"
    if entry.visit_count <= 3:
        return "somewhat familiar"
    if entry.visit_count <= 7:
        return "well known"
    return "overvisited"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = _clean_text(value)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _clean_text(item))]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _display_name(value: Any) -> str:
    text = _clean_text(value)
    for prefix in ("SM_", "ZV_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.replace("_", " ") or "unknown place"


def _known_observation_ids(
    active_zone_ids: tuple[str, ...],
    reachable_zone_ids: tuple[str, ...],
) -> list[str]:
    return _dedupe([*active_zone_ids, *reachable_zone_ids])


def _known_zone_ids(overlay: PlaceMemoryOverlay) -> tuple[str, ...]:
    return tuple(entry.zone_id for entry in overlay.recent(limit=100) if entry.zone_id)


def _candidate_zone_ids(
    reachable_zone_ids: tuple[str, ...],
    overlay: PlaceMemoryOverlay,
    *,
    active_zone_ids: tuple[str, ...],
) -> tuple[str, ...]:
    active = {zone_id.lower() for zone_id in active_zone_ids if zone_id}
    candidates = list(reachable_zone_ids)
    candidates.extend(
        entry.zone_id
        for entry in overlay.entries.values()
        if entry.visit_count <= 0 and entry.zone_id.lower() not in active
    )
    return tuple(_dedupe(candidates))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
