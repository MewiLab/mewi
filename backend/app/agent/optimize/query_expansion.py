"""
Query expansion — produce multiple framings of the same perceptual state
so the model considers alternate angles before picking an intent.

In retrieval, query expansion rewrites a single user query as several
related ones to widen the candidate set. Here we do the analogous move
for *perception*: take the typed need-blocks Slow Mind already sees and
add 1-3 paraphrased framings of the cat's situation that emphasise
*different* drives.

Example, given the same snapshot:
  default situation: "The cat is idle on Boat 2 in Harbor."
  framing #1 (food angle): "Fullness is moderate and the fish is within reach."
  framing #2 (explore angle): "Sea 1 is unvisited and energy is low — a
    short walk would be enough."
  framing #3 (social angle): "Kitten is nearby and trust is uncertain."

Each framing is one short sentence, anchored to typed-block content so
it can't hallucinate. Slow Mind reads them in CURRENT PERCEPTION before
picking the intent — same prompt, broader interpretation.
"""
from __future__ import annotations

from typing import Any


def expand_situation_framings(context: dict[str, Any] | None) -> list[str]:
    """
    Build up to three short paraphrased framings of the current scene,
    one per dominant typed block (food / explore / social). Each framing
    is derived only from data that's already in the context — no model
    call, no hallucinated facts.
    """
    if not isinstance(context, dict):
        return []

    framings: list[str] = []

    food = _first_clause(context.get("food_nearby"))
    if food:
        framings.append(f"Food framing: {food}")

    explore = _first_clause(context.get("relevant_targets")) if not food else ""
    # Prefer explicit frontier framings when present
    if isinstance(context, dict):
        frontier_hint = _frontier_hint(context)
        if frontier_hint:
            framings.append(f"Explore framing: {frontier_hint}")

    social = _first_clause(context.get("social_cues"))
    if social:
        framings.append(f"Social framing: {social}")

    return framings[:3]


def inject_paraphrased_perceptions(
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Return a shallow copy of `context` whose `situation` field has the
    expansion framings appended. Used in place of the raw context when
    callers want the extra angles available to Slow Mind.

    Callers that want to keep the original situation untouched can read
    the appended framings from `query_framings` instead.
    """
    if not isinstance(context, dict):
        return {}

    framings = expand_situation_framings(context)
    if not framings:
        return dict(context)

    augmented = dict(context)
    base = str(augmented.get("situation") or "").rstrip()
    augmented["situation"] = base + "\n" + "\n".join(framings)
    augmented["query_framings"] = framings
    return augmented


def _first_clause(value: Any) -> str:
    """Pull the first descriptive line from a typed block. We drop the
    `target: ...` suffix because the framing is for interpretation, not
    targeting — the model already has target ids in the typed blocks."""
    if isinstance(value, list) and value:
        text = str(value[0]).strip()
    elif isinstance(value, str):
        text = value.strip()
    else:
        return ""
    if ";" in text:
        text = text.split(";", 1)[0]
    return text.rstrip(".") if text else ""


def _frontier_hint(context: dict[str, Any]) -> str:
    """Cheap explore framing: just the first frontier line, sans 'target id'."""
    decision_focus = context.get("decision_focus") or []
    if isinstance(decision_focus, list):
        for line in decision_focus:
            if isinstance(line, str) and "explore" in line.lower():
                return line.strip().rstrip(".")
    return ""
