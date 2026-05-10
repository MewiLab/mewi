"""
Simulate Unity Client Traffic — Semantic Aggregation Pipeline Verification
===========================================================================

Generates realistic tick payloads via an LLM scenario generator, sends them
to the running local FastAPI backend, verifies the 10-to-1 semantic compression
pipeline, and prints a latency report for the Unity frontend team.

Prerequisites
-------------
1. FastAPI server must be running locally:

       uv run uvicorn app.main:app --reload

2. Redis must be reachable (the server depends on it).

How to run
----------
From the ``backend/`` directory:

    uv run python tests/integration/simulate_unity_traffic.py

Output
------
Ticks  1–9  and 11–19  →  {"status": "buffering", "buffered_count": N}
Ticks 10 and 20         →  Full AI reasoning + action payload  (flush tick)

A latency summary is printed at the end with Min / Max / Avg / P95 for:
  • Buffer ticks  — pure in-memory, no DB
  • Flush ticks   — LLM reasoning + Supabase writes (the expensive path)
  • GET /status   — Redis read round-trip
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from tests.integration.payload_generator import generate_scenario_ticks

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL    = "http://localhost:8000/api/v1/agent"
TICK_COUNT  = 20
BUFFER_SIZE = 10
TICK_DELAY  = 0.15        # seconds between ticks

# ANSI colour helpers
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Scenario definitions ──────────────────────────────────────────────────────

@dataclass
class Scenario:
    creature_id: str
    label:       str
    description: str


SCENARIOS: list[Scenario] = [
    Scenario(
        creature_id = "cat_anxious",
        label       = "Anxious Cat",
        description = (
            "A highly anxious cat is crouching in a corner of a living room. "
            "A loud, unknown human is walking closer from the north, now at 4 m and closing. "
            "The cat's fear rises steadily. By tick 10 the human is at 1.5 m and the cat "
            "considers fleeing south toward a hiding spot. "
            "By tick 20 the cat has retreated and the human has moved away."
        ),
    ),
    Scenario(
        creature_id = "cat_avoidant",
        label       = "Avoidant Cat",
        description = (
            "A naturally avoidant cat is sitting near a window exit, watching its familiar owner "
            "from across the room (5 m south). The owner is moving slowly toward the cat. "
            "The cat's trust is low but stable; curiosity increases slightly as the owner "
            "crouches down. By tick 15 the owner is at 2 m and the cat considers approaching. "
            "By tick 20 the cat takes a tentative step forward."
        ),
    ),
]


# ── Latency collector ─────────────────────────────────────────────────────────

@dataclass
class LatencyRecord:
    """Accumulated HTTP round-trip times (ms) per operation type."""
    buffer_ms: list[float] = field(default_factory=list)  # ticks 1-9, 11-19
    flush_ms:  list[float] = field(default_factory=list)  # ticks 10, 20  (LLM + DB write)
    status_ms: list[float] = field(default_factory=list)  # GET /status   (Redis read)

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
        reasoning = (resp.get("reasoning") or "")[:120]
        action    = resp.get("action") or {}
        detail    = f"action={action}  reasoning='{reasoning}…'"
        colour, tag = GREEN, "FLUSH "
    else:
        detail    = f"buffered_count={resp.get('buffered_count', '?')}"
        colour, tag = YELLOW, "BUFFER"

    print(f"  [{colour}{tag}{RESET}] tick={tick_num:>2}  ({elapsed_ms:>7.1f} ms)  {detail}")


def _check_buffer(tick_num: int, resp: dict[str, Any]) -> bool:
    ok = resp.get("status") == "buffering"
    if not ok:
        print(f"  {RED}[WARN] tick {tick_num}: expected status='buffering', got {resp}{RESET}")
    return ok


def _check_flush(tick_num: int, resp: dict[str, Any]) -> bool:
    ok = resp.get("status") != "buffering" and resp.get("action") is not None
    if not ok:
        print(f"  {RED}[WARN] tick {tick_num}: expected flush payload, got {resp}{RESET}")
    return ok


# ── Core simulation ────────────────────────────────────────────────────────────

def simulate_scenario(
    scenario: Scenario,
    ticks: list[dict],
    session: requests.Session,
) -> LatencyRecord:
    """Run one creature's 20-tick scenario and return raw latency samples."""
    _header(f"{scenario.label}  (id={scenario.creature_id})")
    print(f"  Scenario: {scenario.description[:90]}…\n")

    tick_url   = f"{BASE_URL}/tick/{scenario.creature_id}"
    status_url = f"{BASE_URL}/status/{scenario.creature_id}"

    record = LatencyRecord()
    buffer_passed = flush_passed = 0

    for i, payload in enumerate(ticks[:TICK_COUNT], start=1):
        is_flush = (i % BUFFER_SIZE == 0)

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

        _log_tick(i, is_flush, elapsed_ms, resp)

        if is_flush:
            record.flush_ms.append(elapsed_ms)
            if _check_flush(i, resp):
                flush_passed += 1
        else:
            record.buffer_ms.append(elapsed_ms)
            if _check_buffer(i, resp):
                buffer_passed += 1

        time.sleep(TICK_DELAY)

    expected_buffer = TICK_COUNT - (TICK_COUNT // BUFFER_SIZE)
    expected_flush  = TICK_COUNT // BUFFER_SIZE
    print(f"\n  Buffering checks : {buffer_passed}/{expected_buffer}")
    print(f"  Flush checks     : {flush_passed}/{expected_flush}")

    # ── GET /status — Redis read round-trip ───────────────────────────────────
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


# ── Latency report ─────────────────────────────────────────────────────────────

def _print_report(total: LatencyRecord) -> None:
    buf = _stats(total.buffer_ms)
    flu = _stats(total.flush_ms)
    sts = _stats(total.status_ms)

    W = 58
    bar    = "═" * W
    divider= "─" * W

    def row(label: str, value: str) -> str:
        return f"  {label:<28}{value}"

    def ms_row(label: str, v: float) -> str:
        return row(label, f"{v:>8.1f} ms")

    print(f"\n{BOLD}{CYAN}╔{bar}╗{RESET}")
    print(f"{BOLD}{CYAN}║{'  LATENCY REPORT FOR UNITY TEAM':^{W}}║{RESET}")
    print(f"{BOLD}{CYAN}╠{bar}╣{RESET}")

    # Buffer ticks
    print(f"{BOLD}{CYAN}║{'  Buffer ticks  (in-memory, no DB)':^{W}}║{RESET}")
    print(f"{CYAN}║  {divider}║{RESET}")
    print(f"{CYAN}║{row('  Samples', f'{buf[\"n\"]:>8}'):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Min', buf['min']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Max', buf['max']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Avg', buf['avg']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  P95', buf['p95']):>{W+2}}║{RESET}")

    print(f"{BOLD}{CYAN}╠{bar}╣{RESET}")

    # Flush ticks
    print(f"{BOLD}{CYAN}║{'  Flush ticks  (LLM reasoning + Supabase writes)':^{W}}║{RESET}")
    print(f"{CYAN}║  {divider}║{RESET}")
    print(f"{CYAN}║{row('  Samples', f'{flu[\"n\"]:>8}'):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Min', flu['min']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Max', flu['max']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Avg', flu['avg']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  P95', flu['p95']):>{W+2}}║{RESET}")
    print(f"{CYAN}║  {'Note: most of this is LLM time. Server logs show':^{W-2}}║{RESET}")
    print(f"{CYAN}║  {'[DB WRITE] lines for pure Supabase latency.':^{W-2}}║{RESET}")

    print(f"{BOLD}{CYAN}╠{bar}╣{RESET}")

    # GET /status
    print(f"{BOLD}{CYAN}║{'  GET /status  (Redis read round-trip)':^{W}}║{RESET}")
    print(f"{CYAN}║  {divider}║{RESET}")
    print(f"{CYAN}║{row('  Samples', f'{sts[\"n\"]:>8}'):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Min', sts['min']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Max', sts['max']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  Avg', sts['avg']):>{W+2}}║{RESET}")
    print(f"{CYAN}║{ms_row('  P95', sts['p95']):>{W+2}}║{RESET}")
    print(f"{CYAN}║  {'(Unity polls this endpoint for animation state)':^{W-2}}║{RESET}")

    print(f"{BOLD}{CYAN}╚{bar}╝{RESET}\n")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{BOLD}Unity Traffic Simulator — LLM-Driven Scenario Edition{RESET}")
    print(f"Base URL  : {BASE_URL}")
    print(f"Ticks/cat : {TICK_COUNT}  (flush every {BUFFER_SIZE} ticks)")
    print(f"Creatures : {', '.join(s.creature_id for s in SCENARIOS)}")
    print(f"\n{BOLD}Step 1 — Generating payloads via LLM…{RESET}")

    scenario_ticks: list[tuple[Scenario, list[dict]]] = []
    for scenario in SCENARIOS:
        print(f"\n  [{scenario.creature_id}]")
        ticks = generate_scenario_ticks(scenario.description, count=TICK_COUNT)
        scenario_ticks.append((scenario, ticks))

    print(f"\n{BOLD}Step 2 — Sending ticks to backend…{RESET}")

    total = LatencyRecord()
    with requests.Session() as session:
        session.headers["Content-Type"] = "application/json"
        for scenario, ticks in scenario_ticks:
            record = simulate_scenario(scenario, ticks, session)
            total.merge(record)

    print(f"\n{BOLD}{GREEN}Simulation complete.{RESET}")
    _print_report(total)


if __name__ == "__main__":
    main()
