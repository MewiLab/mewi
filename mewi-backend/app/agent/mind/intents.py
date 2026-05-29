from __future__ import annotations

from typing import Any


INTENT_EXPLORE = "EXPLORE"
INTENT_SEEK_FOOD = "SEEK_FOOD"
INTENT_SEEK_PLAYER = "SEEK_PLAYER"
INTENT_SOCIALIZE = "SOCIALIZE"
INTENT_INVESTIGATE = "INVESTIGATE"
INTENT_REST = "REST"
INTENT_SAFETY = "SAFETY"
INTENT_IDLE = "IDLE"
INTENT_LEGACY_PLAN = "LEGACY_PLAN"

KNOWN_INTENTS = {
    INTENT_EXPLORE,
    INTENT_SEEK_FOOD,
    INTENT_SEEK_PLAYER,
    INTENT_SOCIALIZE,
    INTENT_INVESTIGATE,
    INTENT_REST,
    INTENT_SAFETY,
    INTENT_IDLE,
    INTENT_LEGACY_PLAN,
}

_INTENT_ALIASES = {
    "FOOD": INTENT_SEEK_FOOD,
    "EAT": INTENT_SEEK_FOOD,
    "HUNGER": INTENT_SEEK_FOOD,
    "PLAYER": INTENT_SEEK_PLAYER,
    "HUMAN": INTENT_SEEK_PLAYER,
    "SEEK_HUMAN": INTENT_SEEK_PLAYER,
    "SOCIAL": INTENT_SOCIALIZE,
    "INSPECT": INTENT_INVESTIGATE,
    "SNIFF": INTENT_INVESTIGATE,
    "RESTING": INTENT_REST,
    "SLEEP": INTENT_REST,
    "SAFE": INTENT_SAFETY,
    "FEAR": INTENT_SAFETY,
    "FLEE": INTENT_SAFETY,
    "WAIT": INTENT_IDLE,
}


__all__ = [
    "INTENT_EXPLORE",
    "INTENT_IDLE",
    "INTENT_INVESTIGATE",
    "INTENT_LEGACY_PLAN",
    "INTENT_REST",
    "INTENT_SAFETY",
    "INTENT_SEEK_FOOD",
    "INTENT_SEEK_PLAYER",
    "INTENT_SOCIALIZE",
    "KNOWN_INTENTS",
    "clean_text",
    "normalize_intent",
]


def normalize_intent(value: Any, *, default: str = INTENT_IDLE) -> str:
    text = clean_text(value).upper().replace("-", "_").replace(" ", "_")
    if not text:
        return default
    if text in KNOWN_INTENTS:
        return text
    return _INTENT_ALIASES.get(text, default)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())
