"""
Life balance — surface drives that have gone unattended for too long.

The intent selector can over-favor the loudest current cue, which silently
starves quieter drives (curiosity, social, rest). A healthy cat life rotates
through all of them. This module scans Short Term Memory and produces small
prompt-injectable hints for whichever drive has been ignored the longest.

The signal is "ticks since this drive was served." We infer it from the
intent history captured in STM's `action:` aspects. No new snapshot data
required — works against the existing memory_context.

Output is a small list of strings that the caller can append to the DECISION
FOCUS block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())

# Map each cat need to the intent that serves it.
NEED_KEYS: dict[str, tuple[str, ...]] = {
    "food":      ("SEEK_FOOD",),
    "curiosity": ("EXPLORE", "INVESTIGATE"),
    "social":    ("SEEK_PLAYER", "SOCIALIZE"),
    "rest":      ("REST",),
    "safety":    ("SAFETY",),
}

# How many ticks of neglect before we start nudging. Tuned for our 3s
# selector cadence; at 4 ticks, that's about 12s of single-drive lock-in.
_NEGLECT_THRESHOLD = 4

# Per-need phrasing for the focus hint. Phrased as opportunities, not
# commands, so the selector can still override if a real drive is urgent.
_NEED_HINTS: dict[str, str] = {
    "curiosity": "She hasn't explored in a while — EXPLORE is a strong option if no drive is urgent.",
    "social":    "She hasn't socialized in a while — SOCIALIZE or SEEK_PLAYER is a strong option if calm.",
    "rest":      "She hasn't rested in a while — REST is a strong option if energy is low.",
}


@dataclass(frozen=True)
class LifeBalanceReport:
    """Per-need neglect count (ticks since the need was last served).
    Higher = more neglected. Drives over _NEGLECT_THRESHOLD become hints."""
    ticks_since: dict[str, int]

    def neglected(self) -> list[str]:
        """Names of drives currently above the neglect threshold."""
        return [
            name for name, ticks in self.ticks_since.items()
            if ticks >= _NEGLECT_THRESHOLD
        ]


_INTENT_PATTERN = re.compile(r"Next intent ([A-Z_]+)", re.IGNORECASE)


def compute_life_balance(memory_context: dict[str, Any] | None) -> LifeBalanceReport:
    """
    Walk the most recent served intents (oldest first → newest last) and
    count ticks since each drive was last served. Drives never served in the
    visible window get ticks_since == window_size.
    """
    intents = _intent_history(memory_context)
    window = max(1, len(intents))

    ticks_since: dict[str, int] = {need: window for need in NEED_KEYS}

    # Walk newest → oldest so the first time we see a drive's intent is
    # the most recent occurrence, and ticks_since == its index.
    for index, intent in enumerate(reversed(intents)):
        for need, need_intents in NEED_KEYS.items():
            if intent in need_intents and ticks_since[need] == window:
                ticks_since[need] = index

    return LifeBalanceReport(ticks_since=ticks_since)


def life_balance_focus_lines(memory_context: dict[str, Any] | None) -> list[str]:
    """
    Prompt-ready hint lines for DECISION FOCUS, one per neglected drive.
    Returns [] when nothing is unbalanced — the focus block stays untouched.
    """
    report = compute_life_balance(memory_context)
    return [hint for need in report.neglected() if (hint := _NEED_HINTS.get(need))]


def _intent_history(memory_context: dict[str, Any] | None) -> list[str]:
    """Served intents, oldest-first, robust to STM consolidation.

    Prefers the raw-event trail (it carries the structured intent and
    survives LLM summarization of the STM text); falls back to parsing the
    `action:` STM lines for older call sites / tests that only set those.
    """
    if isinstance(memory_context, dict):
        events = memory_context.get("recent_raw_events")
        if isinstance(events, list):
            intents: list[str] = []
            for event in events:
                payload = event.get("payload") if isinstance(event, dict) else None
                decision = payload.get("intent_decision") if isinstance(payload, dict) else None
                intent = clean_text((decision or {}).get("intent")).upper()
                if intent:
                    intents.append(intent)
            if intents:
                return intents

    parsed: list[str] = []
    for line in _action_lines(memory_context):
        match = _INTENT_PATTERN.search(line)
        if match is not None:
            parsed.append(match.group(1).upper())
    return parsed


def _action_lines(memory_context: dict[str, Any] | None) -> list[str]:
    """Pluck the `action: ...` STM entries out of either the flat
    `short_term_lines` list or the typed `short_term` dict."""
    if not isinstance(memory_context, dict):
        return []

    flat = memory_context.get("short_term_lines")
    if isinstance(flat, list):
        return [str(line) for line in flat if isinstance(line, str) and line.startswith("action")]

    short_term = memory_context.get("short_term")
    if not isinstance(short_term, dict):
        return []
    bucket = short_term.get("action")
    if not isinstance(bucket, list):
        return []
    out: list[str] = []
    for item in bucket:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if text:
                out.append(f"action: {text}")
    return out
