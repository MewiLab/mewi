"""
Regex-based signal extractors for narrative action / feedback text.

These read the human-readable strings emitted by
`app.agent.mind.context.format_previous_action_result` (and similar
narrative formatters) and return simple booleans the rest of the codebase
can use to override or augment numeric snapshot fields.

Add new signals here rather than in callers; keep this module the single
source of truth for "did the cat just do X" narrative detection.
"""
from __future__ import annotations

import re

_ATE_PATTERN = re.compile(r"\byou\s+took\s+a\s+bite\b", re.IGNORECASE)
_DRANK_PATTERN = re.compile(r"\byou\s+(?:drank|took\s+a\s+drink)\b", re.IGNORECASE)
_FLED_PATTERN = re.compile(r"\byou\s+(?:fled|moved\s+away)\b", re.IGNORECASE)
_FAILED_REACH_PATTERN = re.compile(
    r"\byou\s+(?:tried\s+to\s+reach|tried\s+to\s+move|got\s+stuck|tried\s+to\s+eat[^.]+couldn't)\b",
    re.IGNORECASE,
)


def recently_ate(text: str | None) -> bool:
    """True if the narrative says the cat took a bite of something."""
    return bool(text) and bool(_ATE_PATTERN.search(text))


def recently_drank(text: str | None) -> bool:
    """True if the narrative says the cat drank."""
    return bool(text) and bool(_DRANK_PATTERN.search(text))


def recently_fled(text: str | None) -> bool:
    """True if the narrative says the cat fled or moved away from a threat."""
    return bool(text) and bool(_FLED_PATTERN.search(text))


def recently_failed_to_reach(text: str | None) -> bool:
    """True if the narrative reports a stuck / failed movement attempt."""
    return bool(text) and bool(_FAILED_REACH_PATTERN.search(text))
