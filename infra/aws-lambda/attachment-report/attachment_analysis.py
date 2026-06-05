"""Attachment-analysis core for the `attachment-report` Lambda.

Self-contained copy of the agent path in
``mewi-backend/app/services/report/attachment_client.py`` (ADR-014 names this as
the future EventBridge/SQS -> Lambda hand-off). The backend keeps its in-process
copy; this one is trimmed for Lambda:

  * input comes from the invocation event (raw ``session`` objects), not from the
    mewi-report filesystem, so there is no ``MEWI_REPORT_ROOT`` / cwd dance;
  * the agent gets the compact digest in the prompt and is given **no** file
    tools (nothing to read inside the Lambda sandbox);
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


def summarize_sessions(
    payloads: list[dict[str, Any]],
    player_id: str | None = None,
) -> dict[str, Any]:
    """Condense raw Unity traces into a compact, agent-ready digest.

    Drops per-event boilerplate and the large raw event rows, keeping only what
    the attachment skill scores from: per-cat trust arcs, action mix, and
    player-distance stats. The human-controlled cat is the one whose ``cat_id``
    equals ``player_id`` (the report slug); its stream is the dependent variable.
    """
    sessions = sorted(
        (_as_session(p) for p in payloads),
        key=lambda s: s.get("session_index") or 0,
    )
    out: list[dict[str, Any]] = []
    for s in sessions:
        events = s.get("events") or []
        cats: dict[str, dict[str, Any]] = {}
        for e in events:
            cid = e.get("cat_id") or "unknown"
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
            action = e.get("action")
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
        player_cat = cats.pop(player_id, None) if player_id else None
        out.append(
            {
                "session_index": s.get("session_index"),
                "duration_seconds": round(s.get("duration_seconds") or 0, 1),
                "event_count": len(events),
                "player": _digest_cat(player_cat) if player_cat else None,
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
        "The player is ALSO a cat: the human-controlled cat is the one whose "
        f"`cat_id` equals the report_slug (`{resolved_slug}`). In each session, "
        "`player` is that cat's stream — the dependent variable, i.e. the human's "
        "response — and `other_cats` are the AI-controlled stimulus. Read the "
        "player's action mix and the stimulus cats' `distance_to_player_m` as the "
        "Strange-Situation signals. If `player` is null and `player_tagged` is "
        "false, the player cat was NOT tagged in this trace: say so explicitly and "
        "lower confidence rather than inventing player behavior.\n\n"
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


# ── Agent run ────────────────────────────────────────────────────────────────
async def run_agent(prompt: str, skill: str, model: str | None) -> str:
    """Drive the Claude Agent SDK and return the agent's final text."""
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ImportError(
            "claude-agent-sdk is not installed in the Lambda bundle. "
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

    agent_env = {
        key: value
        for key in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")
        if (value := os.getenv(key))
    }

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=[],                       # no files to read inside the sandbox
        permission_mode="bypassPermissions",    # non-interactive batch run
        model=_attachment_model(model),
        env=agent_env,
    )

    final_text = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    final_text += block.text + "\n"
        elif isinstance(message, ResultMessage):
            result = getattr(message, "result", None)
            if isinstance(result, str) and result.strip():
                final_text = result
    return final_text


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
