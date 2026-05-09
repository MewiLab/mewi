"""
Simulate Unity Client Traffic — Semantic Aggregation Pipeline Verification
===========================================================================

Generates realistic tick payloads via an LLM scenario generator, sends them
to the running local FastAPI backend, and verifies the 10-to-1 semantic
compression pipeline.

Prerequisites
-------------
1. FastAPI server must be running locally:

       uv run uvicorn app.main:app --reload

2. Redis must be reachable (the server depends on it).

How to run
----------
From the ``backend/`` directory:

    uv run python tests/integration/simulate_unity_traffic.py

Expected output
---------------
Ticks  1–9  and 11–19  →  {"status": "buffering", "buffered_count": N}
Ticks 10 and 20         →  Full AI reasoning + action payload  (flush tick)

The LLM-generated payloads carry real mood/entity context, so the agent's
reasoning on flush ticks should now reflect the scenario (fearful response,
avoidance, etc.) rather than the previous generic "environment is safe."

After tick 20 the GET /status/{creature_id} endpoint is called to confirm
that the real-time state was persisted correctly in Redis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
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


# ── Logging helpers ────────────────────────────────────────────────────────────

def _header(text: str) -> None:
    bar = "═" * 62
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}")


def _log_tick(tick_num: int, is_flush: bool, elapsed_s: float, resp: dict[str, Any]) -> None:
    ms = elapsed_s * 1000
    if is_flush:
        reasoning = (resp.get("reasoning") or "")[:120]
        action    = resp.get("action") or {}
        detail    = f"action={action}  reasoning='{reasoning}…'"
        colour, tag = GREEN, "FLUSH "
    else:
        detail    = f"buffered_count={resp.get('buffered_count', '?')}"
        colour, tag = YELLOW, "BUFFER"

    print(f"  [{colour}{tag}{RESET}] tick={tick_num:>2}  ({ms:>7.1f} ms)  {detail}")


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

def simulate_scenario(scenario: Scenario, ticks: list[dict], session: requests.Session) -> None:
    _header(f"{scenario.label}  (id={scenario.creature_id})")
    print(f"  Scenario: {scenario.description[:90]}…\n")

    tick_url   = f"{BASE_URL}/tick/{scenario.creature_id}"
    status_url = f"{BASE_URL}/status/{scenario.creature_id}"

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
            return
        except requests.exceptions.HTTPError as exc:
            print(f"\n{RED}[ERROR] HTTP {exc.response.status_code} on tick {i}: "
                  f"{exc.response.text[:300]}{RESET}\n")
            return
        except Exception as exc:
            print(f"\n{RED}[ERROR] tick {i}: {type(exc).__name__}: {exc}{RESET}\n")
            return
        finally:
            elapsed = time.perf_counter() - t0

        _log_tick(i, is_flush, elapsed, resp)

        if is_flush:
            if _check_flush(i, resp):
                flush_passed += 1
        else:
            if _check_buffer(i, resp):
                buffer_passed += 1

        time.sleep(TICK_DELAY)

    expected_buffer = TICK_COUNT - (TICK_COUNT // BUFFER_SIZE)
    expected_flush  = TICK_COUNT // BUFFER_SIZE
    print(f"\n  Buffering checks : {buffer_passed}/{expected_buffer}")
    print(f"  Flush checks     : {flush_passed}/{expected_flush}")

    # ── Confirm Redis state via GET /status ────────────────────────────────
    print(f"\n  {BOLD}Querying real-time status from Redis…{RESET}")
    try:
        r = session.get(status_url, timeout=10)
        r.raise_for_status()
        print(f"  {GREEN}GET /status → {r.json()}{RESET}")
    except Exception as exc:
        print(f"  {RED}GET /status failed: {exc}{RESET}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{BOLD}Unity Traffic Simulator — LLM-Driven Scenario Edition{RESET}")
    print(f"Base URL  : {BASE_URL}")
    print(f"Ticks/cat : {TICK_COUNT}  (flush every {BUFFER_SIZE} ticks)")
    print(f"Creatures : {', '.join(s.creature_id for s in SCENARIOS)}")
    print(f"\n{BOLD}Step 1 — Generating payloads via LLM…{RESET}")

    # Generate all scenario payloads upfront so we don't mix generation
    # latency with HTTP timing during the actual simulation.
    scenario_ticks: list[tuple[Scenario, list[dict]]] = []
    for scenario in SCENARIOS:
        print(f"\n  [{scenario.creature_id}]")
        ticks = generate_scenario_ticks(scenario.description, count=TICK_COUNT)
        scenario_ticks.append((scenario, ticks))

    print(f"\n{BOLD}Step 2 — Sending ticks to backend…{RESET}")

    with requests.Session() as session:
        session.headers["Content-Type"] = "application/json"
        for scenario, ticks in scenario_ticks:
            simulate_scenario(scenario, ticks, session)

    print(f"\n{BOLD}{GREEN}Simulation complete.{RESET}\n")


if __name__ == "__main__":
    main()
