from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.world.presence import CatPresence


@dataclass(frozen=True)
class WorldStateSnapshot:
    """Read-only view of WorldState used by graph nodes."""

    cats: dict[str, CatPresence]
    now: float

    def cats_in_zone(self, zone_id: str, *, exclude: str = "") -> list[CatPresence]:
        if not zone_id:
            return []
        key = zone_id.lower()
        excluded = exclude.lower()
        out: list[CatPresence] = []
        for presence in self.cats.values():
            if presence.creature_id.lower() == excluded:
                continue
            if presence.zone_id and presence.zone_id.lower() == key:
                out.append(presence)
        return out


class WorldState:
    """Process-global coarse world model.

    Single-writer per cat: each tick goes through the per-creature lock
    before mutating `cats`. Reads are lock-free — graph nodes always
    consume a `WorldStateSnapshot` copy.
    """

    def __init__(self, *, event_buffer: int = 200) -> None:
        self._cats: dict[str, CatPresence] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=event_buffer)
        self._locks: dict[str, asyncio.Lock] = {}

    # ─── ingest ───────────────────────────────────────────────────────────

    async def ingest_tick(
        self,
        creature_id: str,
        snapshot: dict[str, Any],
        *,
        now: float | None = None,
    ) -> CatPresence:
        if not creature_id:
            raise ValueError("creature_id is required")

        observed_at = now if now is not None else time.time()
        lock = self._locks.setdefault(creature_id, asyncio.Lock())
        async with lock:
            presence = self._cats.get(creature_id) or CatPresence(creature_id=creature_id)
            presence = self._update_presence(presence, snapshot, observed_at)
            self._cats[creature_id] = presence
            self._record_step_events(creature_id, snapshot, observed_at)
            return presence

    # ─── read ─────────────────────────────────────────────────────────────

    def snapshot(self, *, now: float | None = None) -> WorldStateSnapshot:
        return WorldStateSnapshot(
            cats=dict(self._cats),
            now=now if now is not None else time.time(),
        )

    def get(self, creature_id: str) -> CatPresence | None:
        return self._cats.get(creature_id)

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return list(self._events)[-limit:]

    # ─── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _update_presence(
        presence: CatPresence,
        snapshot: dict[str, Any],
        observed_at: float,
    ) -> CatPresence:
        place_context = snapshot.get("place_context") or {}
        spatial = snapshot.get("spatial_context") or {}
        self_view = snapshot.get("self") or {}
        mood = snapshot.get("mood") or {}
        action_result = snapshot.get("action_result") or {}
        request_id = _clean(snapshot.get("requestId") or snapshot.get("request_id"))
        tick_value = int(snapshot.get("tick", presence.last_tick) or 0)

        zone_id = _clean(place_context.get("current_zone_id")) or _last_zone_id(spatial)
        active_zone_ids = tuple(_string_list(place_context.get("active_zone_ids"))) \
            or tuple(_zone_ids(spatial))
        approx_xy = _approx_xy(self_view)
        last_action, last_target, last_at = _last_action_from_report(action_result, observed_at)
        if not last_action:
            last_action, last_target, last_at = presence.last_action, presence.last_action_target, presence.last_action_at

        return CatPresence(
            creature_id=presence.creature_id,
            zone_id=zone_id or presence.zone_id,
            active_zone_ids=active_zone_ids or presence.active_zone_ids,
            approx_xy=approx_xy or presence.approx_xy,
            last_action=last_action,
            last_action_target=last_target,
            last_action_at=last_at,
            mood={k: float(v) for k, v in mood.items() if isinstance(v, (int, float))} or presence.mood,
            last_request_id=request_id or presence.last_request_id,
            last_tick=tick_value or presence.last_tick,
        )

    def _record_step_events(
        self,
        creature_id: str,
        snapshot: dict[str, Any],
        observed_at: float,
    ) -> None:
        report = snapshot.get("action_result") or {}
        steps = report.get("steps") if isinstance(report, dict) else None
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            self._events.append({
                "creature_id": creature_id,
                "at": observed_at,
                "action": _clean(step.get("action")),
                "target": _clean(step.get("target")),
                "status": _clean(step.get("status")),
                "reason": _clean(step.get("reason")),
            })


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = _clean(value)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _clean(item))]


def _last_zone_id(spatial: dict[str, Any]) -> str:
    zones = _zone_ids(spatial)
    return zones[-1] if zones else ""


def _zone_ids(spatial: dict[str, Any]) -> list[str]:
    zones = spatial.get("zones") if isinstance(spatial, dict) else None
    if not isinstance(zones, list):
        return []
    out: list[str] = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        zone_id = _clean(zone.get("id"))
        if zone_id:
            out.append(zone_id)
    return out


def _approx_xy(self_view: dict[str, Any]) -> tuple[float, float] | None:
    location = self_view.get("location")
    if isinstance(location, dict):
        x = location.get("x")
        z = location.get("z")
        if isinstance(x, (int, float)) and isinstance(z, (int, float)):
            return (float(x), float(z))
    return None


def _last_action_from_report(
    report: dict[str, Any],
    observed_at: float,
) -> tuple[str, str, float]:
    if not isinstance(report, dict):
        return ("", "", 0.0)
    steps = report.get("steps")
    if not isinstance(steps, list):
        return ("", "", 0.0)
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        action = _clean(step.get("action"))
        if not action:
            continue
        return (
            action,
            _clean(step.get("target")),
            observed_at,
        )
    return ("", "", 0.0)
