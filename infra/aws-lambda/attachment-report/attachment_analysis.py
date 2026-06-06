"""Attachment-analysis core for the `attachment-report` Lambda.

This is the report pipeline's Claude attachment-analysis owner. FastAPI has no
in-process report-analysis copy; it only stores raw sessions and enqueues the
Lambda hand-off.

  * input comes from the invocation event (raw ``session`` objects), not from the
    mewi-report filesystem, so there is no ``MEWI_REPORT_ROOT`` / cwd dance;
  * Claude gets the compact digest in the prompt and no file tools are needed;
  * the bundled ``skills/attachment-analysis/SKILL.md`` is the operating method.

Keep the scoring/summarisation logic in sync with the backend module when it
changes — both must emit the same ``attachment_analysis`` contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from report_processor import PLAYER_CAT_ACTION_SCHEMA

# SKILL.md ships next to this module inside the Lambda zip.
SKILL_PATH = Path(__file__).resolve().parent / "skills" / "attachment-analysis" / "SKILL.md"


def _attachment_model(model: str | None = None) -> str | None:
    """Resolve the model: explicit arg > env override > SDK default (None)."""
    return (
        model
        or os.getenv("MEWI_REPORT_ATTACHMENT_MODEL", "").strip()
        or os.getenv("CLAUDE_AGENT_MODEL", "").strip()
        or None
    )


def load_skill() -> str:
    if not SKILL_PATH.exists():
        raise FileNotFoundError(f"Skill not found in Lambda bundle: {SKILL_PATH}")
    return SKILL_PATH.read_text(encoding="utf-8")


# ── Compaction (keep the raw event bulk away from the agent) ─────────────────
def _as_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept a full ``{schema_version, user_id, source, session}`` payload or a
    bare ``session`` object, and return the inner session dict either way."""
    inner = payload.get("session")
    return inner if isinstance(inner, dict) else payload


def _measure(value: Any) -> float | None:
    """Treat the ``-1`` sentinel (no reading) as missing for distance/speed."""
    return float(value) if isinstance(value, (int, float)) and value > -1 else None


def _digest_cat(c: dict[str, Any]) -> dict[str, Any]:
    dists = c["distances"]
    first, last = c["trust_first"], c["trust_last"]
    return {
        "trust_start": first,
        "trust_end": last,
        "trust_min": c["trust_min"],
        "trust_max": c["trust_max"],
        "trust_net": (last - first) if first is not None and last is not None else None,
        "actions": dict(sorted(c["actions"].items(), key=lambda kv: (-kv[1], kv[0]))),
        "samples": c["samples"],
        "distance_to_player_m": (
            {
                "min": round(min(dists), 2),
                "mean": round(sum(dists) / len(dists), 2),
                "max": round(max(dists), 2),
            }
            if dists
            else None
        ),
    }


def _new_player_digest() -> dict[str, Any]:
    return {
        "actions": defaultdict(int),
        "action_families": defaultdict(int),
        "targets": defaultdict(int),
        "samples": 0,
    }


def _digest_player(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "actions": dict(sorted(p["actions"].items(), key=lambda kv: (-kv[1], kv[0]))),
        "action_families": dict(sorted(p["action_families"].items(), key=lambda kv: (-kv[1], kv[0]))),
        "targets": dict(sorted(p["targets"].items(), key=lambda kv: (-kv[1], kv[0]))),
        "samples": p["samples"],
    }


def _player_family(action: str) -> str:
    spec = PLAYER_CAT_ACTION_SCHEMA.get(action)
    if spec:
        return spec["family"]
    return "unknown" if action.startswith("player_") else ""


def _is_player_event(event: dict[str, Any]) -> bool:
    action = str(event.get("action") or "")
    return event.get("actor") == "player_cat" or action.startswith("player_")


def summarize_sessions(
    payloads: list[dict[str, Any]],
    player_id: str | None = None,
) -> dict[str, Any]:
    """Condense raw Unity traces into a compact, agent-ready digest.

    Drops per-event boilerplate and the large raw event rows, keeping only what
    the attachment skill scores from: player-cat action mix, per-cat trust arcs,
    and player-distance stats. In raw v2, the human-controlled cat is represented
    by ``actor == "player_cat"`` rows. The report ``user_id`` / slug is not a
    creature id and must not be used as a ``cat_id`` lookup.
    """
    sessions = sorted(
        (_as_session(p) for p in payloads),
        key=lambda s: s.get("session_index") or 0,
    )
    out: list[dict[str, Any]] = []
    for s in sessions:
        events = s.get("events") or []
        cats: dict[str, dict[str, Any]] = {}
        player = _new_player_digest()
        for e in events:
            action = e.get("action")
            if _is_player_event(e):
                player["samples"] += 1
                if action:
                    action = str(action)
                    player["actions"][action] += 1
                    family = _player_family(action)
                    if family:
                        player["action_families"][family] += 1
                target_id = e.get("target_id") or (e.get("params") or {}).get("target_id")
                if target_id:
                    player["targets"][str(target_id)] += 1
                continue

            if e.get("actor") != "cat":
                continue

            cid = e.get("cat_id") or e.get("actor_id") or "unknown"
            c = cats.setdefault(
                cid,
                {
                    "actions": defaultdict(int),
                    "trust_first": None,
                    "trust_last": None,
                    "trust_min": None,
                    "trust_max": None,
                    "distances": [],
                    "samples": 0,
                },
            )
            c["samples"] += 1
            if action:
                c["actions"][action] += 1
            tb, ta = e.get("trust_before"), e.get("trust_after")
            if c["trust_first"] is None and isinstance(tb, (int, float)):
                c["trust_first"] = tb
            if isinstance(ta, (int, float)):
                c["trust_last"] = ta
                c["trust_min"] = ta if c["trust_min"] is None else min(c["trust_min"], ta)
                c["trust_max"] = ta if c["trust_max"] is None else max(c["trust_max"], ta)
            dist = _measure((e.get("params") or {}).get("distance_to_player_m"))
            if dist is not None:
                c["distances"].append(dist)
        out.append(
            {
                "session_index": s.get("session_index"),
                "duration_seconds": round(s.get("duration_seconds") or 0, 1),
                "event_count": len(events),
                "player": _digest_player(player) if player["samples"] else None,
                "other_cats": {cid: _digest_cat(c) for cid, c in sorted(cats.items())},
                "multi_cat_encounters": s.get("multi_cat_encounters") or [],
            }
        )
    return {
        "session_count": len(out),
        "player_id": player_id,
        "player_tagged": any(s["player"] for s in out),
        "sessions": out,
    }


def _infer_slug(payloads: list[dict[str, Any]]) -> str | None:
    for p in payloads:
        for key in ("report_slug", "user_id"):
            if isinstance(p.get(key), str) and p[key]:
                return p[key]
    return None


def build_prompt(slug: str | None, payloads: list[dict[str, Any]]) -> str:
    """The per-run task. The SKILL.md (passed as system prompt) holds the method."""
    resolved_slug = slug or _infer_slug(payloads) or "unknown"
    digest_json = json.dumps(
        summarize_sessions(payloads, player_id=resolved_slug), indent=2, ensure_ascii=False
    )
    return (
        "Run the `attachment-analysis` skill on the player below.\n\n"
        f"report_slug: {resolved_slug}\n\n"
        "You are given a COMPACT DIGEST of the player's Unity sessions (per-cat "
        "trust arcs, action mix, and distance stats) — NOT the raw event log, "
        "which is large and mostly boilerplate. Treat these derived numbers as "
        "the session facts.\n\n"
        "The player is ALSO a cat, but the report_slug is only report identity. "
        "In raw v2, the player stream is made of events whose `actor` is "
        "`player_cat` or whose action starts with `player_`; do NOT infer the "
        f"player from a `cat_id` equal to `{resolved_slug}`. In each session, "
        "`player` is the human-controlled action stream and `other_cats` are the "
        "AI-controlled stimulus/response streams. Read the player's action mix, "
        "action families, targets, and the stimulus cats' `distance_to_player_m` "
        "as Strange-Situation-inspired game signals. If `player` is null and "
        "`player_tagged` is false, the player cat was not recorded in this trace: "
        "say so explicitly and lower confidence rather than inventing player "
        "behavior.\n\n"
        "You are running in a Lambda sandbox with no report files available, so "
        "score only from the digest below — do not attempt to read other files.\n\n"
        "Follow the skill's steps: derive the Strange-Situation signals, score the "
        "four leanings, choose the top leaning, and write 3-4 evidence cards that "
        "each cite a real number from the digest below.\n\n"
        "Return ONLY the final `attachment_analysis` object as a single fenced "
        "```json code block, matching the skill's output contract exactly "
        "(type, modifier, summary, evidence[], scores, confidence, caveat). "
        "Do not write any files.\n\n"
        "SESSION DIGEST:\n```json\n" + digest_json + "\n```\n"
    )


# ── Claude run ───────────────────────────────────────────────────────────────
async def run_agent(prompt: str, skill: str, model: str | None) -> str:
    """Call Claude directly and return the final text.

    The Claude Agent SDK bundles a large CLI binary that is unsuitable for this
    Lambda zip. This direct Messages API path keeps the same skill/system prompt
    contract without shipping that binary.
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ImportError(
            "anthropic is not installed in the Lambda bundle. "
            "Add it to requirements.txt (and set ANTHROPIC_API_KEY)."
        ) from exc

    system_prompt = (
        "You are the Mewi attachment-analysis agent. Follow the skill below "
        "exactly; it is your operating procedure. Stay grounded, non-clinical, "
        "and honest about confidence.\n\n"
        "================ SKILL: attachment-analysis ================\n"
        f"{skill}\n"
        "===========================================================\n"
    )

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for attachment-report")

    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=_attachment_model(model) or "claude-sonnet-4-6",
        max_tokens=1800,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )

    parts: list[str] = []
    for block in response.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


# ── Output extraction ────────────────────────────────────────────────────────
def extract_analysis(text: str) -> dict[str, Any]:
    """Pull the attachment_analysis JSON object out of the agent's reply."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not candidates:
        span = _last_json_object(text)
        candidates = [span] if span else []

    for blob in reversed(candidates):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "type" in obj and "scores" in obj:
            return obj
    raise ValueError("Could not find a valid attachment_analysis JSON object in the agent reply.")


def _last_json_object(text: str) -> str | None:
    depth, start, span = 0, -1, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start != -1:
                span = text[start : i + 1]
    return span


# ── Sync entrypoint (called by handler.py) ───────────────────────────────────
def analyze_sessions(
    user_id: str,
    sessions: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Run the agent over raw ``session`` objects and return the
    ``attachment_analysis`` dict. Synchronous so the Lambda handler can call it
    without managing an event loop itself.
    """
    skill = load_skill()
    slug = _infer_slug(sessions) or user_id
    prompt = build_prompt(slug, sessions)
    reply = asyncio.run(run_agent(prompt, skill, model))
    return extract_analysis(reply)
