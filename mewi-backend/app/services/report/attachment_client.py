"""
Agent-driven attachment analysis (single source: backend).

Runs the `attachment-analysis` skill
(app/services/report/skills/attachment-analysis/SKILL.md) through the Claude
Agent SDK over a player's raw Unity session traces and emits the
`attachment_analysis` JSON block the report site renders.

This is the LLM alternative to the deterministic `_attachment_analysis` rule in
``processor.py``. Per ADR-014, all report-derivation code lives in the backend;
``mewi-report`` is render-only and only reads the processed JSON written here.

The skill is the *instructions*; this module is the *runner*. It:
  1. loads the SKILL.md as the agent's procedure,
  2. ingests raw Unity session data (by slug, explicit paths, or stdin),
  3. lets the agent read the report tree for grounding (ADR-007, processed data),
  4. extracts and prints the resulting attachment_analysis object.

Paths follow the same ``MEWI_REPORT_ROOT`` convention as ``app/api/deps.py`` so
the backend stays the one place that knows where mewi-report lives.

Usage (from mewi-backend/):
    python -m app.services.report.attachment_client --slug vanillasky_01
    python -m app.services.report.attachment_client --raw path/to/01_s1.json
    curl -s .../report/session | python -m app.services.report.attachment_client --raw -
    python -m app.services.report.attachment_client --slug vanillasky_01 --write

Requires the optional dependency:  pip install 'backend[report-agent]'
(and ANTHROPIC_API_KEY in the environment).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────────
# attachment_client.py lives at mewi-backend/app/services/report/.
SERVICE_DIR = Path(__file__).resolve().parent              # app/services/report
SKILL_PATH = SERVICE_DIR / "skills" / "attachment-analysis" / "SKILL.md"
BACKEND_DIR = Path(__file__).resolve().parents[3]

# Keep this unset by default so the Claude Agent SDK / Claude Code runtime uses
# its configured model. Override with MEWI_REPORT_ATTACHMENT_MODEL when needed.
DEFAULT_MODEL: str | None = None


def _load_backend_env() -> None:
    """Expose backend .env values to the Claude SDK in native dev runs."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(BACKEND_DIR / ".env", override=False)


def _attachment_model(model: str | None = None) -> str | None:
    return (
        model
        or os.getenv("MEWI_REPORT_ATTACHMENT_MODEL", "").strip()
        or os.getenv("CLAUDE_AGENT_MODEL", "").strip()
        or None
    )


def _mewi_report_root() -> Path:
    """Resolve the mewi-report project root (mirror of app/api/deps.py)."""
    configured = os.getenv("MEWI_REPORT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # app/services/report/attachment_client.py -> report -> services -> app
    #   -> mewi-backend -> repo root
    return Path(__file__).resolve().parents[4] / "mewi-report"


def _env_path(env_key: str, default: Path) -> Path:
    configured = os.getenv(env_key, "").strip()
    return Path(configured).expanduser().resolve() if configured else default


_load_backend_env()

REPORT_ROOT = _mewi_report_root()
PIPELINE_DIR = REPORT_ROOT / "pipeline"
SESSIONS_DIR = _env_path("MEWI_REPORT_RAW_SESSION_DIR", PIPELINE_DIR / "raw_data" / "sessions")
PROCESSED_DIR = _env_path("MEWI_REPORT_PROCESSED_DIR", PIPELINE_DIR / "processed_data")


# ── Input loading ────────────────────────────────────────────────────────────
def load_skill() -> str:
    if not SKILL_PATH.exists():
        raise FileNotFoundError(f"Skill not found: {SKILL_PATH}")
    return SKILL_PATH.read_text(encoding="utf-8")


def load_raw_sessions(slug: str | None, raw: list[str] | None) -> list[dict[str, Any]]:
    """Collect raw Unity session payloads from a slug dir, explicit paths, or stdin."""
    payloads: list[dict[str, Any]] = []

    for item in raw or []:
        if item == "-":
            payloads.extend(_coerce_sessions(json.load(sys.stdin)))
            continue
        path = Path(item)
        if path.is_dir():
            for f in sorted(path.glob("*.json")):
                payloads.extend(_coerce_sessions(json.loads(f.read_text(encoding="utf-8"))))
        elif path.exists():
            payloads.extend(_coerce_sessions(json.loads(path.read_text(encoding="utf-8"))))
        else:
            raise FileNotFoundError(f"Raw input not found: {path}")

    if slug:
        slug_dir = SESSIONS_DIR / slug
        if not slug_dir.is_dir():
            raise FileNotFoundError(f"No raw sessions for slug '{slug}': {slug_dir}")
        for f in sorted(slug_dir.glob("*.json")):
            payloads.extend(_coerce_sessions(json.loads(f.read_text(encoding="utf-8"))))

    if not payloads:
        raise ValueError("No raw session data provided. Use --slug, --raw, or pipe JSON to --raw -.")
    return payloads


def _coerce_sessions(data: Any) -> list[dict[str, Any]]:
    """Accept either one session file ({...}) or a list of them."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        return [data]
    return []


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

    Drops the per-event boilerplate (`meta`, the constant `trigger`) and the
    large raw event rows, keeping only what the attachment skill scores from:
    per-cat trust arcs, action mix, and player-distance stats. This is the
    parsing/analysis step that lets the agent reason over derived facts instead
    of a ~64KB raw log it does not need to see.

    The player is *also* a cat: the human-controlled cat is the one whose
    ``cat_id`` equals ``player_id`` (the report slug / user_id). Its stream is
    the dependent variable (the player's response); the rest are the AI stimulus.
    Each session is split into ``player`` and ``other_cats`` accordingly. When no
    cat matches ``player_id``, ``player`` is ``null`` (the player cat was not
    tagged in that trace) and every cat falls under ``other_cats``.
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
        "You MAY also read the report tree for cross-checks and grounding (e.g. "
        f"`pipeline/processed_data/report_{resolved_slug}.json`, "
        f"`pipeline/report_overrides/{resolved_slug}.json`, and the ADR-007 doc) "
        "using the Read/Glob tools — paths are relative to the working directory.\n\n"
        "Follow the skill's steps: derive the Strange-Situation signals, score the "
        "four leanings, choose the top leaning, and write 3-4 evidence cards that "
        "each cite a real number from the digest below.\n\n"
        "Return ONLY the final `attachment_analysis` object as a single fenced "
        "```json code block, matching the skill's output contract exactly "
        "(type, modifier, summary, evidence[], scores, confidence, caveat). "
        "Do not write any files.\n\n"
        "SESSION DIGEST:\n```json\n" + digest_json + "\n```\n"
    )


def _infer_slug(payloads: list[dict[str, Any]]) -> str | None:
    for p in payloads:
        for key in ("report_slug", "user_id"):
            if isinstance(p.get(key), str) and p[key]:
                return p[key]
    return None


# ── Agent run ────────────────────────────────────────────────────────────────
async def run_agent(prompt: str, skill: str, model: str | None, verbose: bool) -> str:
    """Drive the Claude Agent SDK and return the agent's final text."""
    _load_backend_env()
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
            "claude-agent-sdk is not installed. Run: pip install 'backend[report-agent]' "
            "(and set ANTHROPIC_API_KEY)."
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
        allowed_tools=["Read", "Glob", "Grep"],   # read-only: no writes from the agent
        permission_mode="bypassPermissions",        # non-interactive batch run
        cwd=str(REPORT_ROOT),                       # so `pipeline/...` paths resolve
        model=_attachment_model(model),
        env=agent_env,
    )

    final_text = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if verbose:
                        print(block.text, file=sys.stderr)
                    final_text += block.text + "\n"
        elif isinstance(message, ResultMessage):
            result = getattr(message, "result", None)
            if isinstance(result, str) and result.strip():
                final_text = result
    return final_text


# ── Sync entrypoint (used by processor.py "agent" mode) ──────────────────────
def analyze_sessions(
    user_id: str,
    sessions: list[dict[str, Any]],
    *,
    model: str | None = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Run the agent over already-loaded raw ``session`` objects and return the
    ``attachment_analysis`` dict. Synchronous so ``processor.process_report``
    can call it without knowing about asyncio.
    """
    skill = load_skill()
    slug = _infer_slug(sessions) or user_id
    prompt = build_prompt(slug, sessions)
    reply = _run_blocking(run_agent(prompt, skill, model, verbose=False))
    return extract_analysis(reply)


def _run_blocking(coro: Any) -> Any:
    """Run an async coroutine to completion from sync code.

    If no event loop is running, use ``asyncio.run``. If one is already running
    (e.g. inside the FastAPI request that triggers processing), run it in a
    short-lived worker thread so we never touch the live loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


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


def write_into_processed(slug: str, analysis: dict[str, Any]) -> Path:
    """Merge the analysis into pipeline/processed_data/report_<slug>.json."""
    target = PROCESSED_DIR / f"report_{slug}.json"
    if not target.exists():
        raise FileNotFoundError(f"Processed report not found: {target}")
    data = json.loads(target.read_text(encoding="utf-8"))
    data["attachment_analysis"] = analysis
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


# ── CLI ──────────────────────────────────────────────────────────────────────
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the attachment-analysis skill via the Claude Agent SDK.")
    p.add_argument("--slug", help="Report slug; reads <mewi-report>/pipeline/raw_data/sessions/<slug>/.")
    p.add_argument("--raw", nargs="+", help="Raw session JSON file(s)/dir, or '-' for stdin.")
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model id. Defaults to MEWI_REPORT_ATTACHMENT_MODEL, CLAUDE_AGENT_MODEL, or the SDK default.",
    )
    p.add_argument("--write", action="store_true", help="Merge result into the processed report.")
    p.add_argument("--verbose", action="store_true", help="Stream agent thinking to stderr.")
    return p.parse_args(argv)


async def main_async(args: argparse.Namespace) -> int:
    skill = load_skill()
    payloads = load_raw_sessions(args.slug, args.raw)
    slug = args.slug or _infer_slug(payloads)
    prompt = build_prompt(slug, payloads)

    reply = await run_agent(prompt, skill, args.model, args.verbose)
    analysis = extract_analysis(reply)

    print(json.dumps(analysis, indent=2, ensure_ascii=False))

    if args.write:
        if not slug:
            print("Cannot --write without a resolvable slug.", file=sys.stderr)
            return 2
        path = write_into_processed(slug, analysis)
        print(f"\nWrote attachment_analysis into {path}", file=sys.stderr)
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except (FileNotFoundError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
