from __future__ import annotations

from typing import Any

from app.agent.creature_runtime import CreatureRuntimeState
from app.agent.mind.context import clean_text, format_previous_action_result
from app.services.perception.semantic_service import SemanticService


__all__ = ["build_structured_context"]


def build_structured_context(state: CreatureRuntimeState) -> dict[str, Any]:
    """Turn Unity's raw tick into the backend's schema-light context object."""

    raw = state.get("raw_payload", {}) or {}
    semantic_context = SemanticService().build_prompt_context(raw)
    place_context = raw.get("place_context") if isinstance(raw.get("place_context"), dict) else {}
    spatial_context = raw.get("spatial_context") if isinstance(raw.get("spatial_context"), dict) else {}
    navigation_context = raw.get("navigation_context") if isinstance(raw.get("navigation_context"), dict) else {}

    return {
        "request_id": clean_text(raw.get("requestId") or raw.get("request_id")),
        "agent_id": clean_text(raw.get("agent_id")),
        "tick": int(raw.get("tick", state.get("tick", 0)) or 0),
        "semantic_context": semantic_context,
        "previous_action_result": format_previous_action_result(raw.get("action_result")),
        "place": {
            "current_zone_id": clean_text(place_context.get("current_zone_id")),
            "active_zone_ids": _string_list(place_context.get("active_zone_ids")),
            "reachable_zone_ids": _string_list(place_context.get("reachable_zone_ids")),
            "zone_ids": _zone_ids(spatial_context),
        },
        "navigation": {
            "zone_routes": _zone_routes(navigation_context),
        },
        "body": {
            "mood": _numeric_dict(raw.get("mood")),
            "health": _numeric_dict(raw.get("health")),
        },
        "signals": raw.get("feelings") if isinstance(raw.get("feelings"), dict) else {},
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := clean_text(item))]


def _zone_ids(spatial_context: dict[str, Any]) -> list[str]:
    zones = spatial_context.get("zones")
    if not isinstance(zones, list):
        return []
    out: list[str] = []
    for zone in zones:
        if isinstance(zone, dict) and (zone_id := clean_text(zone.get("id"))):
            out.append(zone_id)
    return out


def _numeric_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(raw)
        for key, raw in value.items()
        if isinstance(raw, (int, float))
    }


def _zone_routes(navigation_context: dict[str, Any]) -> list[dict[str, Any]]:
    routes = navigation_context.get("zone_routes")
    if not isinstance(routes, list):
        return []

    out: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        route_id = clean_text(route.get("id"))
        if not route_id:
            continue
        out.append({
            "id": route_id,
            "status": clean_text(route.get("status")),
            "reason": clean_text(route.get("reason")),
            "distance": _optional_float(route.get("distance")),
            "path_length": _optional_float(route.get("path_length")),
        })
    return out


def _optional_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return float(value)
