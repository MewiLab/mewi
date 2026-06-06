from __future__ import annotations

from typing import Any


def build_langgraph_memory_state(
    *,
    memory_context: dict[str, Any] | None,
    place_memory_context: dict[str, Any] | None,
    world_view: dict[str, Any] | None,
    social_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Group retrieved memory by agent-facing memory role."""

    memory = memory_context if isinstance(memory_context, dict) else {}
    return {
        "recent": {
            "memory_ticks": memory.get("memory_ticks"),
            "recent_perceptions": memory.get("recent_perceptions") or [],
            "short_term_lines": memory.get("short_term_lines") or [],
            "longterm": memory.get("longterm") or [],
        },
        "working": memory.get("short_term") or {},
        "episodic": memory.get("recent_raw_events") or [],
        "spatial": {
            "places_visited": memory.get("places_visited", 0),
            "place_memory": place_memory_context or {},
        },
        "relationship": {
            "world_view": world_view or {},
            "social_context": social_context or {},
        },
    }
