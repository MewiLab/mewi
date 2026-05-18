"""
Simulate Unity Client Traffic — Background Pipeline Verification
================================================================

Sends tick payloads to the running FastAPI backend, verifies the async Redis
buffer → embedding → Supabase pipeline, and prints a latency report.

Prerequisites
-------------
1. FastAPI server running with feature flags enabled:

       ENABLE_MEMORY_PIPELINE=True \\
       ENABLE_REFLECTION_CYCLE=True \\
       BUFFER_FLUSH_THRESHOLD=6 \\
       uv run uvicorn app.main:app --reload

   Set BUFFER_FLUSH_THRESHOLD ≤ --snapshots so the backend flushes immediately
   instead of waiting 120 seconds for the fallback timer.

2. Redis and Supabase must be reachable.

Usage
-----
From the ``backend/`` directory:

    # 50 snapshots, sinusoidal stubs — no LLM cost (recommended for CI)
    uv run python scripts/simulate_unity_traffic.py -s 50 -m fallback

    # 50 snapshots, LLM-generated payloads (5 batches × 10 ticks each)
    uv run python scripts/simulate_unity_traffic.py -s 50 -m llm

    # Skip the 120 s wait if BUFFER_FLUSH_THRESHOLD=10 is set on the server
    uv run python scripts/simulate_unity_traffic.py -s 50 -m fallback --flush-wait 15

    # Latency report only — no Supabase check
    uv run python scripts/simulate_unity_traffic.py -m fallback --skip-verify

Pipeline verification (Steps 3 & 4)
-------------------------------------
After sending all snapshots the script polls GET /status until the background
flush pipeline signals completion, then queries ``perception_snapshots`` in
Supabase and asserts that:
  • One or more rows exist for each creature (created after the run started).
  • The ``embedding`` column is populated for every row.
If ENABLE_REFLECTION_CYCLE=True is detected, ``memory_summaries`` is also
checked for each creature.
"""

from __future__ import annotations

import os

# Set feature flags before any app import so @lru_cache in get_settings() picks
# them up for this process (Supabase client, settings reads, etc.).
# NOTE: the *server* process must also be started with these vars — they cannot
# be injected into an already-running process from here.
os.environ.setdefault("ENABLE_MEMORY_PIPELINE", "True")
os.environ.setdefault("ENABLE_REFLECTION_CYCLE", "True")

import argparse
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.payload_generator import (
    _sinusoidal_fallback,
    generate_scenario_ticks,
)

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL             = "http://localhost:8000/api/v1/agent"
BUFFER_SIZE_DEFAULT  = 10   # server's default flush threshold when no env override is set
TICK_DELAY           = 0.15  # seconds between successive tick POSTs

GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Scenario definitions ───────────────────────────────────────────────────────

@dataclass
class Scenario:
    creature_id: str
    label:       str
    description: str
    arc:         str  # "happy" | "stressed" — drives fallback math and LLM framing


SCENARIOS: list[Scenario] = [
    Scenario(
        creature_id = "cat_01",
        label       = "Happy Arc — cat_01",
        arc         = "happy",
        description = (
            "A cat in a warm living room begins in a completely neutral, curious state "
            "with no prior emotional history — treat every mood value as starting from scratch. "
            "In the first third of ticks it discovers a favourite toy (a small feather wand) "
            "on the floor and its curiosity and energy rise as it begins to bat at it. "
            "By the midpoint the cat is at peak play: pouncing, chasing, and vocalising with "
            "high social mood and rising trust. "
            "In the final third the play gradually winds down; the cat settles into calm "
            "satisfaction — high happiness, low fear, moderate tiredness, and a gentle increase "
            "in hunger after all the activity."
        ),
    ),
    Scenario(
        creature_id = "cat_02",
        label       = "Stressed Arc — cat_02",
        arc         = "stressed",
        description = (
            "A cat in a quiet apartment begins in a completely neutral, relaxed state "
            "with no prior emotional history — treat every mood value as starting from scratch. "
            "In the very first few ticks a sudden, sharp sound (a nearby car alarm) erupts "
            "without warning: fear spikes sharply and the cat sprints to hide under the bed, "
            "crouching with ears flat, tail tucked, and trust collapsing. "
            "Through the middle ticks the environment falls silent again, but the cat remains "
            "frozen — curiosity suppressed, energy draining, social mood near zero. "
            "By the final ticks the acute fear has faded into prolonged sadness and low-energy "
            "anxiety; hunger has risen (the cat has not eaten) and it makes no attempt "
            "to leave its hiding spot."
        ),
    ),
]


# ── Latency collector ──────────────────────────────────────────────────────────

@dataclass
class LatencyRecord:
    """Accumulated HTTP round-trip times (ms) per operation type."""
    buffer_ms: list[float] = field(default_factory=list)
    flush_ms:  list[float] = field(default_factory=list)
    status_ms: list[float] = field(default_factory=list)

    def merge(self, other: "LatencyRecord") -> None:
        self.buffer_ms.extend(other.buffer_ms)
        self.flush_ms.extend(other.flush_ms)
        self.status_ms.extend(other.status_ms)


def _stats(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"min": 0, "max": 0, "avg": 0, "p95": 0, "n": 0}
    s = sorted(samples)
    p95_idx = max(0, int(len(s) * 0.95) - 1)
    return {
        "min": s[0],
        "max": s[-1],
        "avg": statistics.mean(s),
        "p95": s[p95_idx],
        "n":   len(s),
    }


# ── Logging helpers ────────────────────────────────────────────────────────────

def _header(text: str) -> None:
    bar = "═" * 62
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}")


def _log_tick(tick_num: int, is_flush: bool, elapsed_ms: float, resp: dict[str, Any]) -> None:
    if is_flush:
        if resp.get("status") == "processing":
            detail = "pipeline queued — poll /status for result"
        else:
            reasoning = (resp.get("reasoning") or "")[:120]
            action    = resp.get("action") or {}
            detail    = f"action={action}  reasoning='{reasoning}…'"
        colour, tag = GREEN, "FLUSH "
    else:
        detail      = f"buffered_count={resp.get('buffered_count', '?')}"
        colour, tag = YELLOW, "BUFFER"

    print(f"  [{colour}{tag}{RESET}] tick={tick_num:>2}  ({elapsed_ms:>7.1f} ms)  {detail}")


def _check_buffer(tick_num: int, resp: dict[str, Any]) -> bool:
    ok = resp.get("status") == "buffering"
    if not ok:
        print(f"  {RED}[WARN] tick {tick_num}: expected status='buffering', got {resp}{RESET}")
    return ok


def _check_flush(tick_num: int, resp: dict[str, Any]) -> bool:
    ok = resp.get("status") in ("processing", "ok") or resp.get("action") is not None
    if not ok:
        print(f"  {RED}[WARN] tick {tick_num}: expected flush (processing/action), got {resp}{RESET}")
    return ok


# ── Core simulation ────────────────────────────────────────────────────────────

def simulate_scenario(
    scenario: Scenario,
    ticks: list[dict],
    session: requests.Session,
    tick_count: int,
    flush_threshold: int,
) -> LatencyRecord:
    """
    Run one creature's tick sequence and return raw latency samples.

    flush_threshold: the BUFFER_FLUSH_THRESHOLD the server was started with.
        Ticks at multiples of this value are expected to return HTTP 202
        (processing).  Pass 0 when tick_count < BUFFER_SIZE_DEFAULT so that
        no in-loop flush is expected and the 120 s timer is used instead.
    """
    _header(f"{scenario.label}  (id={scenario.creature_id})")
    print(f"  Scenario: {scenario.description[:90]}…\n")

    tick_url   = f"{BASE_URL}/tick/{scenario.creature_id}"
    status_url = f"{BASE_URL}/status/{scenario.creature_id}"

    record = LatencyRecord()
    buffer_passed = flush_passed = 0
    pipeline_disabled_suspected = False

    for i, payload in enumerate(ticks[:tick_count], start=1):
        is_flush = flush_threshold > 0 and (i % flush_threshold == 0)

        t0 = time.perf_counter()
        try:
            r = session.post(tick_url, json=payload, timeout=60)
            r.raise_for_status()
            resp = r.json()
        except requests.exceptions.ConnectionError:
            print(f"\n{RED}[ERROR] Cannot reach {tick_url}{RESET}")
            print(f"{RED}        Start the server:  uv run uvicorn app.main:app --reload{RESET}\n")
            return record
        except requests.exceptions.HTTPError as exc:
            print(f"\n{RED}[ERROR] HTTP {exc.response.status_code} on tick {i}: "
                  f"{exc.response.text[:300]}{RESET}\n")
            return record
        except Exception as exc:
            print(f"\n{RED}[ERROR] tick {i}: {type(exc).__name__}: {exc}{RESET}\n")
            return record
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000

        # ── Stale-buffer detection on the very first tick ─────────────────────
        if i == 1:
            count = resp.get("buffered_count", 0) or 0
            if count > 1:
                print(
                    f"  {YELLOW}[WARN] buffered_count={count} on tick 1 — "
                    f"{count - 1} stale item(s) left from a previous run.{RESET}\n"
                    f"  {YELLOW}       This shifts the flush boundary.  "
                    f"Flush the buffer (restart Redis or wait for the 120 s timer) "
                    f"before re-running for deterministic results.{RESET}\n"
                )

        _log_tick(i, is_flush, elapsed_ms, resp)

        if is_flush:
            record.flush_ms.append(elapsed_ms)
            if _check_flush(i, resp):
                flush_passed += 1
            elif resp.get("status") == "buffering":
                # Count kept growing past threshold → pipeline likely disabled.
                pipeline_disabled_suspected = True
        else:
            record.buffer_ms.append(elapsed_ms)
            if _check_buffer(i, resp):
                buffer_passed += 1

        time.sleep(TICK_DELAY)

    expected_buffer = tick_count - (tick_count // flush_threshold) if flush_threshold else tick_count
    expected_flush  = tick_count // flush_threshold if flush_threshold else 0
    print(f"\n  Buffering checks : {buffer_passed}/{expected_buffer}")
    if expected_flush > 0:
        print(f"  Flush checks     : {flush_passed}/{expected_flush}")
        if pipeline_disabled_suspected:
            print(
                f"\n  {RED}[DIAG] All expected flush ticks returned 'buffering'.{RESET}\n"
                f"  {RED}       The server is likely running with ENABLE_MEMORY_PIPELINE=False.{RESET}\n"
                f"  {RED}       Restart with:  ENABLE_MEMORY_PIPELINE=True "
                f"BUFFER_FLUSH_THRESHOLD={flush_threshold} uv run uvicorn app.main:app --reload{RESET}"
            )
    else:
        print(
            f"  Flush checks     : N/A  "
            f"({tick_count} snapshots < server threshold — 120 s timer flush expected)"
        )

    print(f"\n  {BOLD}Querying real-time status from Redis…{RESET}")
    try:
        t0 = time.perf_counter()
        r  = session.get(status_url, timeout=10)
        r.raise_for_status()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        record.status_ms.append(elapsed_ms)
        print(f"  {GREEN}GET /status → {r.json()}  ({elapsed_ms:.1f} ms){RESET}")
    except Exception as exc:
        print(f"  {RED}GET /status failed: {exc}{RESET}")

    return record


# ── Pipeline flush wait ────────────────────────────────────────────────────────

def _wait_for_pipeline_flush(
    creature_ids: list[str],
    session: requests.Session,
    timeout_s: float,
    threshold_hint: int | None = None,
) -> bool:
    """
    Poll GET /status for all creatures and mark each one done as soon as
    is_thinking is False.  Does NOT require observing a True→False transition,
    so creatures whose pipelines complete before polling starts are detected on
    the very first poll.

    Returns True when all creatures are confirmed idle within timeout_s.
    """
    _header("Step 3 — Waiting for Background Pipeline Flush")

    print(f"  Timeout       : {timeout_s:.0f}s  |  Poll interval: 5s\n")

    deadline   = time.monotonic() + timeout_s
    flush_done = set()   # creatures confirmed idle
    first_poll = True

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()

        for cid in creature_ids:
            if cid in flush_done:
                continue
            try:
                r = session.get(f"{BASE_URL}/status/{cid}", timeout=10)
                r.raise_for_status()
                is_thinking = r.json().get("is_thinking", False)

                if is_thinking:
                    print(f"\n  [{CYAN}ACTIVE{RESET}] {cid}: pipeline processing…")
                else:
                    note = " (completed before polling started)" if first_poll else ""
                    print(f"\n  [{GREEN}DONE  {RESET}] {cid}: flush complete{note}.")
                    flush_done.add(cid)
            except Exception:
                pass

        first_poll = False

        if len(flush_done) == len(creature_ids):
            break

        print(
            f"  Polling… {remaining:>5.0f}s remaining  "
            f"({len(flush_done)}/{len(creature_ids)} done)       ",
            end="\r",
            flush=True,
        )
        time.sleep(5.0)

    print()  # clear the \r line

    not_done = [c for c in creature_ids if c not in flush_done]
    if not_done:
        print(f"  {YELLOW}[WARN] Flush not confirmed for: {not_done}{RESET}")
        print(f"  {YELLOW}       If Supabase is empty: verify ENABLE_MEMORY_PIPELINE=True on server.{RESET}")
        return False

    print(f"  {GREEN}All creatures flushed.{RESET}")
    return True


# ── Supabase verification ──────────────────────────────────────────────────────

def _verify_supabase(creature_ids: list[str], since: datetime) -> None:
    """
    Query Supabase to assert that the background pipeline inserted rows into
    ``perception_snapshots`` with populated ``embedding`` vectors.

    Creature string IDs (e.g. "cat_01") are converted to deterministic
    UUIDs via uuid5(NAMESPACE_DNS, creature_id) — matching AgentService logic.
    """
    _header("Step 4 — Supabase Pipeline Verification")

    try:
        from app.core.config import get_settings
        from app.core.supabase.client import create_supabase
    except ImportError as exc:
        print(f"  {RED}[ERROR] Cannot import app modules: {exc}{RESET}")
        print(f"  {RED}        Run from backend/ with: uv run python scripts/…{RESET}")
        return

    try:
        client = create_supabase(get_settings())
    except Exception as exc:
        print(f"  {RED}[ERROR] Supabase client init failed: {exc}{RESET}")
        return

    since_iso = since.isoformat()
    snap_passed = snap_failed = 0

    print(f"  Checking perception_snapshots (since {since.strftime('%H:%M:%S UTC')})…\n")

    for creature_id in creature_ids:
        db_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, creature_id))

        try:
            result = (
                client
                .table("perception_snapshots")
                .select("id, summary_text, embedding, created_at")
                .eq("creature_id", db_id)
                .gte("created_at", since_iso)
                .order("created_at", desc=True)
                .limit(10)
                .execute()
            )
            rows = result.data or []
        except Exception as exc:
            print(f"  {RED}[ERROR] {creature_id}: query failed — {exc}{RESET}")
            snap_failed += 1
            continue

        if not rows:
            print(
                f"  {RED}[FAIL] {creature_id} (uuid={db_id[:8]}…): "
                f"0 rows in perception_snapshots since "
                f"{since.strftime('%H:%M:%S')}{RESET}"
            )
            snap_failed += 1
            continue

        embed_ok  = all(bool(row.get("embedding")) for row in rows)
        embed_tag = (
            f"{GREEN}embeddings ✓{RESET}"
            if embed_ok
            else f"{RED}embeddings missing ✗{RESET}"
        )
        print(
            f"  {GREEN}[PASS]{RESET} {creature_id}  "
            f"{len(rows)} snapshot(s)  {embed_tag}"
        )
        if embed_ok:
            snap_passed += 1
        else:
            snap_failed += 1

    # ── Reflection cycle check (optional) ─────────────────────────────────────
    if os.environ.get("ENABLE_REFLECTION_CYCLE", "").lower() in ("true", "1"):
        print(f"\n  Checking memory_summaries (ENABLE_REFLECTION_CYCLE=True)…\n")
        for creature_id in creature_ids:
            db_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, creature_id))
            try:
                result = (
                    client
                    .table("memory_summaries")
                    .select("id, created_at")
                    .eq("creature_id", db_id)
                    .gte("created_at", since_iso)
                    .limit(5)
                    .execute()
                )
                rows = result.data or []
                if rows:
                    print(
                        f"  {GREEN}[PASS]{RESET} {creature_id}: "
                        f"{len(rows)} memory summary/summaries found."
                    )
                else:
                    print(
                        f"  {YELLOW}[INFO]{RESET} {creature_id}: no memory summaries yet — "
                        f"reflection runs after flush and may need extra time."
                    )
            except Exception as exc:
                print(
                    f"  {YELLOW}[INFO]{RESET} {creature_id}: "
                    f"memory_summaries check skipped — {exc}"
                )

    # ── Summary line ───────────────────────────────────────────────────────────
    total  = len(creature_ids)
    colour = GREEN if snap_failed == 0 else RED
    print(f"\n  {colour}Snapshot assertion: {snap_passed}/{total} passed{RESET}")


# ── Latency report ─────────────────────────────────────────────────────────────

def _print_report(total: LatencyRecord) -> None:
    buf = _stats(total.buffer_ms)
    flu = _stats(total.flush_ms)
    sts = _stats(total.status_ms)

    W       = 58
    bar     = "═" * W
    divider = "─" * W

    def row(label: str, value: str) -> str:
        return f"  {label:<28}{value}"

    def ms_row(label: str, v: float) -> str:
        return row(label, f"{v:>8.1f} ms")

    print(f"\n{BOLD}{CYAN}╔{bar}╗{RESET}")
    print(f"{BOLD}{CYAN}║{'  LATENCY REPORT FOR UNITY TEAM':^{W}}║{RESET}")
    print(f"{BOLD}{CYAN}╠{bar}╣{RESET}")

    buf_n = str(buf["n"])
    flu_n = str(flu["n"])
    sts_n = str(sts["n"])

    print(f"{BOLD}{CYAN}║{'  Buffer ticks  (in-memory, no DB)':^{W}}║{RESET}")
    print(f"{CYAN}║  {divider}║{RESET}")
    print(f"{CYAN}║{row('  Samples', buf_n.rjust(8)):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Min', buf['min']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Max', buf['max']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Avg', buf['avg']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  P95', buf['p95']):>{W+2}}║{RESET}")

    print(f"{BOLD}{CYAN}╠{bar}╣{RESET}")

    print(f"{BOLD}{CYAN}║{'  Flush ticks  (202 Accepted — pipeline in background)':^{W}}║{RESET}")
    print(f"{CYAN}║  {divider}║{RESET}")
    print(f"{CYAN}║{row('  Samples', flu_n.rjust(8)):>{W+2}}║{RESET}")
    if flu["n"] > 0:
        print(f"{CYAN}║{ms_row('  Min', flu['min']):>{W+2}}║{RESET}")
        print(f"{CYAN}║{ms_row('  Max', flu['max']):>{W+2}}║{RESET}")
        print(f"{CYAN}║{ms_row('  Avg', flu['avg']):>{W+2}}║{RESET}")
        print(f"{CYAN}║{ms_row('  P95', flu['p95']):>{W+2}}║{RESET}")
        print(f"{CYAN}║  {'LLM reasoning runs after response. Check server logs':^{W-2}}║{RESET}")
        print(f"{CYAN}║  {'for [FLUSH DONE] to see action + reasoning output.':^{W-2}}║{RESET}")
    else:
        print(f"{CYAN}║  {'No in-band flush ticks (snapshots < buffer threshold).':^{W-2}}║{RESET}")
        print(f"{CYAN}║  {'Pipeline was triggered by the 120 s fallback timer.':^{W-2}}║{RESET}")
        print(f"{CYAN}║  {'Set BUFFER_FLUSH_THRESHOLD=<snapshots> to flush immediately.':^{W-2}}║{RESET}")

    print(f"{BOLD}{CYAN}╠{bar}╣{RESET}")

    print(f"{BOLD}{CYAN}║{'  GET /status  (Redis read round-trip)':^{W}}║{RESET}")
    print(f"{CYAN}║  {divider}║{RESET}")
    print(f"{CYAN}║{row('  Samples', sts_n.rjust(8)):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Min', sts['min']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Max', sts['max']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Avg', sts['avg']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  P95', sts['p95']):>{W+2}}║{RESET}")
    print(f"{CYAN}║  {'(Unity polls this endpoint for animation state)':^{W-2}}║{RESET}")

    print(f"{BOLD}{CYAN}╚{bar}╝{RESET}\n")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unity Traffic Simulator — background pipeline verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  # 50 snapshots, no LLM cost, full Supabase verification\n"
            "  uv run python scripts/simulate_unity_traffic.py -m fallback\n\n"
            "  # 50 snapshots, LLM-generated arcs, skip 120 s wait (BUFFER_FLUSH_THRESHOLD=10 on server)\n"
            "  uv run python scripts/simulate_unity_traffic.py -m llm --flush-wait 15\n\n"
            "  # Custom count — fewer ticks for quick smoke-test\n"
            "  uv run python scripts/simulate_unity_traffic.py -s 10 -m fallback --flush-wait 15\n\n"
            "  # Latency report only, no pipeline assertions\n"
            "  uv run python scripts/simulate_unity_traffic.py -m fallback --skip-verify\n"
        ),
    )
    parser.add_argument(
        "-s", "--snapshots",
        type=int,
        default=50,
        metavar="N",
        help=(
            "Number of tick snapshots to send per creature (default: 50). "
            "50 ticks generates 5 pipeline flushes (at BUFFER_FLUSH_THRESHOLD=10) "
            "and sufficient history to trigger a reflection cycle."
        ),
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["llm", "fallback"],
        default="fallback",
        help=(
            "Payload source: 'llm' uses the LLM scenario generator; "
            "'fallback' uses deterministic sinusoidal stubs (no API cost)."
        ),
    )
    parser.add_argument(
        "--flush-wait",
        type=float,
        default=30.0,
        metavar="SECS",
        help=(
            "Seconds to poll for pipeline completion after the last tick "
            "(default: 30). Increase if LangGraph reasoning is slow."
        ),
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip Steps 3 & 4 (pipeline wait + Supabase assertions). Prints latency report only.",
    )
    # Kept for backward-compat; hidden from help.
    parser.add_argument("--no-llm", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.no_llm:
        args.mode = "fallback"

    # Read the server's actual flush threshold from the same .env / environment
    # that the server reads, so flush detection matches the server's real behaviour.
    # Never override this env var here — doing so would shadow .env and break detection.
    try:
        from app.core.config import get_settings
        flush_threshold = get_settings().BUFFER_FLUSH_THRESHOLD
    except Exception:
        flush_threshold = BUFFER_SIZE_DEFAULT

    creatures       = [s.creature_id for s in SCENARIOS]
    mode_label      = "LLM-Driven" if args.mode == "llm" else "Sinusoidal Fallback (no LLM)"
    expected_flushes = args.snapshots // flush_threshold

    print(f"\n{BOLD}Unity Traffic Simulator — {mode_label} Edition{RESET}")
    print(f"Base URL        : {BASE_URL}")
    print(f"Snapshots/cat   : {args.snapshots}")
    print(f"Flush threshold : {flush_threshold}  "
          f"(→ {expected_flushes} flush(es) per creature)")
    print(f"Flush wait      : {args.flush_wait:.0f}s")
    print(f"Skip verify     : {args.skip_verify}")
    print(f"Creatures       : {', '.join(creatures)}")

    # ── Server startup notice ──────────────────────────────────────────────────
    print(f"\n{BOLD}Active server settings (read from .env):{RESET}")
    from app.core.config import get_settings as _gs
    _s = _gs()
    _flags = {
        "ENABLE_MEMORY_PIPELINE":  str(_s.ENABLE_MEMORY_PIPELINE),
        "ENABLE_REFLECTION_CYCLE": str(_s.ENABLE_REFLECTION_CYCLE),
        "BUFFER_FLUSH_THRESHOLD":  str(_s.BUFFER_FLUSH_THRESHOLD),
    }
    for k, v in _flags.items():
        ok = v.lower() in ("true", "1") or v.isdigit()
        colour = GREEN if ok else YELLOW
        print(f"  {colour}{k}={v}{RESET}")

    if not _s.ENABLE_MEMORY_PIPELINE:
        print(
            f"\n  {RED}[WARN] ENABLE_MEMORY_PIPELINE=False — pipeline will not flush."
            f"\n         Set ENABLE_MEMORY_PIPELINE=True in .env and restart the server.{RESET}"
        )

    if expected_flushes == 0:
        print(
            f"\n{BOLD}{YELLOW}Note:{RESET}{YELLOW} {args.snapshots} snapshots < flush threshold "
            f"({flush_threshold}).  Pipeline will be triggered by the 120 s fallback timer.{RESET}"
        )

    # ── Step 1: Generate payloads ──────────────────────────────────────────────
    print(f"\n{BOLD}Step 1 — Generating payloads ({args.mode} mode)…{RESET}")
    scenario_ticks: list[tuple[Scenario, list[dict]]] = []

    if args.mode == "fallback":
        for scenario in SCENARIOS:
            ticks = _sinusoidal_fallback(args.snapshots, arc=scenario.arc)
            print(f"  [{scenario.creature_id}] {args.snapshots} stub(s) ready  [{scenario.arc} arc].")
            scenario_ticks.append((scenario, ticks))
    else:
        for scenario in SCENARIOS:
            print(f"\n  [{scenario.creature_id}]")
            ticks = generate_scenario_ticks(scenario.description, count=args.snapshots)
            scenario_ticks.append((scenario, ticks))

    # ── Step 2: Send ticks ─────────────────────────────────────────────────────
    print(f"\n{BOLD}Step 2 — Sending {args.snapshots} tick(s) per creature to backend…{RESET}")

    # effective_flush_threshold: what we pass to simulate_scenario for per-tick detection.
    # 0 = no in-loop flush expected (total ticks < threshold → timer-only path).
    effective_flush_threshold = flush_threshold if args.snapshots >= flush_threshold else 0

    run_start = datetime.now(timezone.utc)
    total     = LatencyRecord()

    with requests.Session() as session:
        session.headers["Content-Type"] = "application/json"

        for scenario, ticks in scenario_ticks:
            record = simulate_scenario(
                scenario, ticks, session, args.snapshots, effective_flush_threshold
            )
            total.merge(record)

        # ── Step 3: Wait for pipeline flush ───────────────────────────────────
        if not args.skip_verify and args.flush_wait > 0:
            _wait_for_pipeline_flush(
                creature_ids    = creatures,
                session         = session,
                timeout_s       = args.flush_wait,
                threshold_hint  = args.snapshots,
            )

    # ── Step 4: Verify Supabase ────────────────────────────────────────────────
    if not args.skip_verify:
        _verify_supabase(creatures, since=run_start)

    # ── Latency report ─────────────────────────────────────────────────────────
    print(f"\n{BOLD}{GREEN}Simulation complete.{RESET}")
    _print_report(total)


if __name__ == "__main__":
    main()
