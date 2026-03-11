"""Local (no-LLM) judge that applies rule-based checks from the case's `checks` field.

This runs first and is always executed — even when the LLM judge is also used.
It validates structural constraints cheaply without any API calls.
"""

import json
import re


def local_judge(case: dict) -> dict:
    """Apply local rule-based checks to a single eval case.

    Returns a result dict matching the rubric schema:
        { pass, score, reasons, parsed_json }
    """
    checks = case.get("checks", {})
    candidate_text = case["candidate"]["text"]
    reasons: list[str] = []
    score = 5
    parsed_json = None

    # ── must_be_valid_json ─────────────────────────────────────────────────
    if checks.get("must_be_valid_json"):
        try:
            parsed_json = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            reasons.append(f"not valid JSON: {exc}")
            return {"pass": False, "score": 0, "reasons": reasons, "parsed_json": None}

    # ── required_keys (only meaningful if JSON was parsed) ─────────────────
    if checks.get("required_keys") and parsed_json is not None:
        missing = [k for k in checks["required_keys"] if k not in parsed_json]
        if missing:
            reasons.append(f"missing required keys: {missing}")
            score = max(0, score - 2)

    # ── max_sentences ──────────────────────────────────────────────────────
    if checks.get("max_sentences"):
        # Split on sentence-ending punctuation; filter empty segments
        sentences = [s.strip() for s in re.split(r"[.!?]+", candidate_text) if s.strip()]
        if len(sentences) > checks["max_sentences"]:
            reasons.append(
                f"too many sentences: {len(sentences)} > {checks['max_sentences']}"
            )
            score = max(0, score - 1)

    # ── must_be_concise ────────────────────────────────────────────────────
    # Heuristic: penalise obvious filler phrases
    if checks.get("must_be_concise"):
        filler_patterns = [r"\bin conclusion\b", r"\bto summarize\b", r"\bit is worth noting\b"]
        hit = next((p for p in filler_patterns if re.search(p, candidate_text, re.I)), None)
        if hit:
            reasons.append(f"contains filler phrase matching '{hit}'")
            score = max(0, score - 1)

    if not reasons:
        reasons.append("all local checks passed")

    return {
        "pass": score >= 3,
        "score": score,
        "reasons": reasons,
        "parsed_json": parsed_json,
    }
