"""
Agent-assisted cat journal processing.

Input: one cat's raw backend graph logs
(`app/cat_journal/journal/<cat_id>/raw_agent_graph.jsonl`).

Output: a processed `cat_journal` JSON object that reads the cat's own behavior:
intent arcs, action habits, places, social rooms, dialogue, relationships, and
memorable turns.

Usage (from mewi-backend/):
    python -m app.cat_journal.journal_client --cat miso
    python -m app.cat_journal.journal_client --cat miso --write
    python -m app.cat_journal.journal_client --raw app/cat_journal/journal/miso/raw_agent_graph.jsonl
    python -m app.cat_journal.journal_client --cat miso --default

The default path uses the Claude Agent SDK when available. `--default` skips the
agent and emits the deterministic processed journal from `journal_preprocess.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from app.cat_journal.journal_preprocess import (
    DEFAULT_JOURNAL_DIR,
    build_processed_journal,
    load_cat_records,
    load_records,
    preprocess_cat_journal,
    write_processed_journal,
)


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODEL: str | None = None


SYSTEM_PROMPT = """You are the Mewi cat-journal agent.

You process one cat's backend-owned life records. The Python behavior graph is
the source of truth: Unity only reports snapshots and completion feedback.

Write a lively but grounded processed journal about the cat itself. Make it feel
like a living behavioral record: what the cat tends to want, how it moves, how it
handles other cats, what places pull it, and which turns feel story-worthy.

Guardrails:
- Use only the digest facts provided. Do not invent cats, rooms, quotes, places,
  or completed actions.
- Treat dialogue as simulated cat socialization, not human psychology.
- Keep the output useful for a renderer: compact JSON, no markdown outside the
  fenced code block.
- Be more evocative than a metrics report, but every episode and relationship
  must point back to real ticks/counts/lines in the digest.

Return exactly one JSON object with this shape:

{
  "schema_version": "cat_journal.v1",
  "creature_id": "cat id",
  "generated_at": "ISO timestamp or empty",
  "source": {"record_count": 0, "turn_count": 0, "tick_range": {"first": null, "last": null}},
  "title": "short title",
  "subtitle": "one compact source summary",
  "portrait": {
    "one_line": "one vivid, grounded sentence",
    "temperament": ["2-5 tags"],
    "signature_moves": ["action/count snippets"],
    "social_style": "how this cat relates to peers",
    "solitude_style": "how this cat behaves alone"
  },
  "arcs": [
    {"label": "Decision Weather", "detail": "grounded detail"},
    {"label": "Body Language", "detail": "grounded detail"},
    {"label": "Territory", "detail": "grounded detail"},
    {"label": "Social Gravity", "detail": "grounded detail"},
    {"label": "Follow-through", "detail": "grounded detail"}
  ],
  "relationships": [
    {
      "peer_id": "peer",
      "summary": "grounded in shared turns/spoken/heard/bond numbers",
      "spoken_to": 0,
      "heard_from": 0,
      "shared_room_turns": 0,
      "trust": null,
      "affinity": null,
      "key_lines": [{"tick": 0, "from": "cat", "text": "quote"}]
    }
  ],
  "statistics": {
    "turns": {},
    "mainly": {},
    "drive_balance": [],
    "action_balance": [],
    "place_behavior": {},
    "social_behavior": {},
    "execution_behavior": {},
    "badges": []
  },
  "episodes": [
    {
      "tick": 0,
      "title": "short episode title",
      "scene": "what happened, grounded in plan/social/place",
      "intent": {"name": "INTENT"},
      "plan": [{"action": "action", "target": "target", "reason": "reason"}],
      "why_it_matters": "why this turn reveals this cat"
    }
  ],
  "patterns": {
    "intent_mix": [],
    "action_mix": [],
    "places": [],
    "execution": []
  },
  "open_threads": ["future processing questions grounded in the digest"],
  "caveat": "This journal is a behavioral reading of backend graph logs, not a claim about an animal or player outside the simulation."
}
"""


def _load_backend_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(BACKEND_DIR / ".env", override=False)


def _journal_model(model: str | None = None) -> str | None:
    return (
        model
        or os.getenv("MEWI_CAT_JOURNAL_MODEL", "").strip()
        or os.getenv("CLAUDE_AGENT_MODEL", "").strip()
        or None
    )


_load_backend_env()


def build_prompt(creature_id: str, digest: dict[str, Any]) -> str:
    digest_json = json.dumps(digest, indent=2, ensure_ascii=False)
    return (
        "Process this cat's backend journal digest into a `cat_journal.v1` object.\n\n"
        f"creature_id: {creature_id}\n\n"
        "What the graph gave us, already compacted:\n"
        "- slow intent decisions (`intent.name`, target/style/reasoning)\n"
        "- fast mind plan steps and chosen actions\n"
        "- Unity's previous completion feedback\n"
        "- place/zone context\n"
        "- mood and health readings\n"
        "- social rooms, delivered inbox, dialogue, relationship deltas/states\n"
        "- memorable turns selected from the raw graph records\n\n"
        "Use the numbers and ticks directly. Keep the writing lively, but never "
        "invent facts beyond this digest.\n\n"
        "Return ONLY a fenced ```json code block containing the processed journal.\n\n"
        "CAT JOURNAL DIGEST:\n```json\n"
        + digest_json
        + "\n```\n"
    )


async def run_agent(prompt: str, model: str | None, verbose: bool) -> str:
    """Drive the Claude Agent SDK and return the final text."""
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
            "(and set ANTHROPIC_API_KEY), or use --default."
        ) from exc

    agent_env = {
        key: value
        for key in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")
        if (value := os.getenv(key))
    }
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=["Read", "Glob", "Grep"],
        permission_mode="bypassPermissions",
        cwd=str(BACKEND_DIR),
        model=_journal_model(model),
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


def analyze_records(
    creature_id: str,
    records: list[dict[str, Any]],
    *,
    model: str | None = DEFAULT_MODEL,
    use_agent: bool = True,
) -> dict[str, Any]:
    digest = preprocess_cat_journal(records, creature_id=creature_id)
    if not use_agent:
        return build_processed_journal(digest)

    prompt = build_prompt(creature_id, digest)
    reply = _run_blocking(run_agent(prompt, model, verbose=False))
    journal = extract_journal(reply)
    journal.setdefault("schema_version", "cat_journal.v1")
    journal.setdefault("creature_id", creature_id)
    journal.setdefault("source", digest.get("source", {}))
    return journal


def _run_blocking(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def extract_journal(text: str) -> dict[str, Any]:
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not candidates:
        span = _last_json_object(text)
        candidates = [span] if span else []

    for blob in reversed(candidates):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("schema_version") == "cat_journal.v1":
            return obj
        if isinstance(obj, dict) and {"portrait", "episodes", "patterns"} <= set(obj.keys()):
            obj["schema_version"] = "cat_journal.v1"
            return obj
    raise ValueError("Could not find a valid cat_journal.v1 JSON object in the agent reply.")


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process one cat's raw graph journal.")
    parser.add_argument("--cat", help="Creature id; reads app/cat_journal/journal/<cat>/ by default.")
    parser.add_argument("--raw", nargs="+", help="Raw journal JSONL/JSON file(s), directories, or '-' for stdin.")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_JOURNAL_DIR),
        help="Journal root directory. Defaults to app/cat_journal/journal.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model id. Defaults to MEWI_CAT_JOURNAL_MODEL, CLAUDE_AGENT_MODEL, or SDK default.",
    )
    parser.add_argument("--default", action="store_true", help="Skip Claude and use deterministic processing.")
    parser.add_argument("--write", action="store_true", help="Write processed_journal.json next to the raw log.")
    parser.add_argument("--verbose", action="store_true", help="Stream agent text to stderr.")
    return parser.parse_args(argv)


def _load_records_from_args(args: argparse.Namespace) -> tuple[str, list[dict[str, Any]]]:
    if args.raw:
        records: list[dict[str, Any]] = []
        file_inputs: list[str] = []
        for item in args.raw:
            if item == "-":
                records.extend(_coerce_stdin_records(sys.stdin.read()))
            else:
                file_inputs.append(item)
        if file_inputs:
            records.extend(load_records(file_inputs))
        creature_id = args.cat or _infer_creature_id(records)
        if not creature_id:
            raise ValueError("Cannot infer creature id from --raw input; pass --cat.")
        return creature_id, records

    if not args.cat:
        raise ValueError("Pass --cat, --raw, or both.")
    return args.cat, load_cat_records(args.cat, root_dir=args.root)


def _coerce_stdin_records(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in stripped.splitlines():
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
        return records

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("records"), list):
        return [item for item in data["records"] if isinstance(item, dict)]
    return [data] if isinstance(data, dict) else []


def _infer_creature_id(records: list[dict[str, Any]]) -> str:
    for record in records:
        value = record.get("creature_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def main_async(args: argparse.Namespace) -> int:
    creature_id, records = _load_records_from_args(args)
    digest = preprocess_cat_journal(records, creature_id=creature_id)

    if args.default:
        journal = build_processed_journal(digest)
    else:
        prompt = build_prompt(creature_id, digest)
        reply = await run_agent(prompt, args.model, args.verbose)
        journal = extract_journal(reply)
        journal.setdefault("creature_id", creature_id)
        journal.setdefault("source", digest.get("source", {}))

    print(json.dumps(journal, indent=2, ensure_ascii=False))

    if args.write:
        path = write_processed_journal(creature_id, journal, root_dir=args.root)
        print(f"\nWrote processed journal into {path}", file=sys.stderr)
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
