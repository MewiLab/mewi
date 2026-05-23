"""
Plan diversity — score Fast Mind plans against recent history so the
executor can prefer non-repetitive sequences.

When the cat keeps emitting the same plan (smell → go_to fish → eat),
that's usually because the LLM saw the same context and produced the
same answer. We can't change the LLM's determinism, but we *can*:

  - capture a compact signature of each plan (action+target sequence)
  - compare a new candidate against the last N signatures from STM
  - return a novelty score in [0.0, 1.0]: 1.0 = entirely new, 0.0 =
    identical to the last plan

Use:
  - When Fast Mind returns multiple candidates (via temperature > 0 or
    `n` sampling), pick the candidate with the highest novelty score.
  - When Fast Mind returns one candidate, the score still lets the
    executor decide whether to *ask again* for a different plan.

Pure scoring — no LLM calls. Cheap enough to run on every plan.
"""
from __future__ import annotations

import re
from typing import Any


def plan_signature(plan_steps: list[dict[str, Any]] | None) -> tuple[str, ...]:
    """
    Compact tuple of `action[:target]` strings — the same shape used by
    the STM `Next intent X became plan: ...` lines.
    """
    if not isinstance(plan_steps, list):
        return ()
    sig: list[str] = []
    for step in plan_steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "").strip()
        if not action:
            continue
        target = str(step.get("target") or "").strip()
        sig.append(f"{action}:{target}" if target else action)
    return tuple(sig)


def score_plan_novelty(
    candidate: list[dict[str, Any]],
    memory_context: dict[str, Any] | None,
    *,
    window: int = 3,
) -> float:
    """
    Compare candidate plan against the last `window` plans recorded in STM.
    Returns 1.0 if no historic plan matches at all, 0.0 if the candidate
    is identical to the most recent plan, with smoothed scores in between.

    The comparison is per-step (Jaccard-like): novelty = fraction of
    candidate steps that don't appear in any recent plan, averaged over
    the comparison window with a recency weight.
    """
    cand_sig = plan_signature(candidate)
    if not cand_sig:
        return 0.0

    history = _recent_plan_signatures(memory_context, window=window)
    if not history:
        return 1.0

    cand_set = set(cand_sig)
    weighted_overlap = 0.0
    weight_total = 0.0
    # Recent plans matter more — linear weight 1.0, 0.7, 0.4, ...
    for i, past in enumerate(history):
        weight = max(0.0, 1.0 - i * 0.3)
        if weight == 0.0:
            break
        weight_total += weight
        past_set = set(past)
        if not past_set:
            continue
        overlap = len(cand_set & past_set) / max(1, len(cand_set))
        weighted_overlap += weight * overlap

    if weight_total == 0.0:
        return 1.0
    return max(0.0, 1.0 - (weighted_overlap / weight_total))


_PLAN_PATTERN = re.compile(r"became plan:\s*(.+?)\.\s*$")


def _recent_plan_signatures(
    memory_context: dict[str, Any] | None,
    *,
    window: int,
) -> list[tuple[str, ...]]:
    """Parse plan signatures back out of STM action lines. Newest first."""
    if not isinstance(memory_context, dict):
        return []

    lines: list[str]
    flat = memory_context.get("short_term_lines")
    if isinstance(flat, list):
        lines = [str(item) for item in flat if isinstance(item, str)]
    else:
        short_term = memory_context.get("short_term")
        if not isinstance(short_term, dict):
            return []
        bucket = short_term.get("action")
        if not isinstance(bucket, list):
            return []
        lines = [
            str(item.get("text") or "").strip()
            for item in bucket
            if isinstance(item, dict)
        ]

    sigs: list[tuple[str, ...]] = []
    for line in reversed(lines):
        match = _PLAN_PATTERN.search(line)
        if match is None:
            continue
        steps = [step.strip() for step in match.group(1).split("->") if step.strip()]
        if steps:
            sigs.append(tuple(steps))
        if len(sigs) >= window:
            break
    return sigs
