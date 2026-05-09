"""
Simulate Unity Client Traffic — Semantic Aggregation Pipeline Verification
===========================================================================

Sends 20 ticks per creature to the running local FastAPI backend and verifies
that the 10-to-1 semantic compression pipeline is working correctly.

Prerequisites
-------------
1. FastAPI server must be running locally:

       uv run uvicorn app.main:app --reload

2. Redis must be reachable (the server depends on it).

How to run
----------
From the ``backend/`` directory:

    uv run python tests/integration/simulate_unity_traffic.py

Or with a plain Python interpreter (when deps are already installed):

    python tests/integration/simulate_unity_traffic.py

Expected output
---------------
Ticks  1–9  and 11–19  →  {"status": "buffering", "buffered_count": N}
Ticks 10 and 20         →  Full AI reasoning + action payload  (flush tick)

After tick 20 the GET /status/{creature_id} endpoint is queried to confirm
that the real-time state was persisted correctly in Redis.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL    = "http://localhost:8000/api/v1/agent"
TICK_COUNT  = 20
BUFFER_SIZE = 10          # must match the backend BUFFER_SIZE setting
TICK_DELAY  = 0.15        # seconds between ticks — avoids hammering the server

# ANSI colour helpers (silently ignored on terminals without colour support)
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Creature personality profiles ─────────────────────────────────────────────

@dataclass
class CreatureProfile:
    creature_id:   str
    label:         str
    base_mood:     dict[str, float]
    base_location: dict[str, float]
    base_action:   str
    entities:      list[dict[str, Any]] = field(default_factory=list)


CREATURES: list[CreatureProfile] = [
    CreatureProfile(
        creature_id   = "cat_anxious",
        label         = "Anxious Cat",
        base_mood     = {
            "fear": 0.80, "trust": 0.10,
            "curiosity": 0.35, "social": 0.15, "energy": 0.65,
        },
        base_location = {"x": 2.0, "y": 0.0, "z": 1.5},
        base_action   = "crouch",
        entities      = [
            {"id": "human_stranger", "tags": ["human", "unknown"], "distance": 2.8, "direction": "north"},
            {"id": "loud_appliance", "tags": ["object", "noisy"],  "distance": 4.0, "direction": "east"},
        ],
    ),
    CreatureProfile(
        creature_id   = "cat_avoidant",
        label         = "Avoidant Cat",
        base_mood     = {
            "fear": 0.45, "trust": 0.05,
            "curiosity": 0.20, "social": 0.05, "energy": 0.85,
        },
        base_location = {"x": 8.0, "y": 0.0, "z": 6.0},
        base_action   = "walk",
        entities      = [
            {"id": "human_owner", "tags": ["human", "familiar"], "distance": 5.5, "direction": "south"},
            {"id": "window",      "tags": ["object", "exit"],    "distance": 1.2, "direction": "west"},
        ],
    ),
]


# ── Payload factory ────────────────────────────────────────────────────────────

def build_payload(profile: CreatureProfile, tick_index: int) -> dict[str, Any]:
    """
    Build a TickPayload-compatible dict with small per-tick variations to
    simulate genuine movement and mood fluctuation.

    JSON keys use Field aliases from tick.py:
      "requestId" → request_id
      "self"      → self_state
    """
    t = tick_index

    loc = profile.base_location
    location = {
        "x": round(loc["x"] + math.sin(t * 0.4) * 0.3, 3),
        "y": round(loc["y"], 3),
        "z": round(loc["z"] + math.cos(t * 0.3) * 0.25, 3),
    }

    bm = profile.base_mood
    mood = {
        "fear":      round(max(0.0, min(1.0, bm["fear"]      + math.sin(t * 0.7) * 0.06)), 3),
        "trust":     round(max(0.0, min(1.0, bm["trust"]     + math.cos(t * 0.5) * 0.04)), 3),
        "curiosity": round(max(0.0, min(1.0, bm["curiosity"] + math.sin(t * 0.3) * 0.05)), 3),
        "social":    round(max(0.0, min(1.0, bm["social"]    + math.cos(t * 0.6) * 0.03)), 3),
        "energy":    round(max(0.0, min(1.0, bm["energy"]    - t * 0.01)),                  3),
    }

    # Entities drift slightly closer each tick (approaching scenario)
    entities = [
        {**e, "distance": round(max(0.5, e["distance"] - t * 0.04), 2)}
        for e in profile.entities
    ]

    return {
        "requestId": str(uuid.uuid4()),
        "self": {
            "location":       location,
            "current_action": profile.base_action,
        },
        "mood":     mood,
        "health":   {"hunger": round(min(1.0, t * 0.04), 3)},
        "entities": entities,
    }


# ── Logging helpers ────────────────────────────────────────────────────────────

def _header(text: str) -> None:
    bar = "═" * 60
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}")


def _log_tick(tick_num: int, is_flush: bool, elapsed_s: float, resp: dict[str, Any]) -> None:
    ms = elapsed_s * 1000
    if is_flush:
        reasoning = (resp.get("reasoning") or "")[:100]
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

def simulate_creature(profile: CreatureProfile, session: requests.Session) -> None:
    _header(f"{profile.label}  (id={profile.creature_id})")

    tick_url   = f"{BASE_URL}/tick/{profile.creature_id}"
    status_url = f"{BASE_URL}/status/{profile.creature_id}"

    buffer_passed = flush_passed = 0

    for i in range(1, TICK_COUNT + 1):
        payload  = build_payload(profile, i)
        is_flush = (i % BUFFER_SIZE == 0)

        t0 = time.perf_counter()
        try:
            r = session.post(tick_url, json=payload, timeout=60)
            r.raise_for_status()
            resp = r.json()
        except requests.exceptions.ConnectionError:
            print(f"\n{RED}[ERROR] Cannot reach {tick_url}{RESET}")
            print(f"{RED}        Start the server first:  uv run uvicorn app.main:app --reload{RESET}\n")
            return
        except requests.exceptions.HTTPError as exc:
            print(f"\n{RED}[ERROR] HTTP {exc.response.status_code} on tick {i}: {exc.response.text[:300]}{RESET}\n")
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
    print(f"\n{BOLD}Unity Traffic Simulator — 10-to-1 Semantic Aggregation Test{RESET}")
    print(f"Base URL  : {BASE_URL}")
    print(f"Ticks/cat : {TICK_COUNT}  (flush every {BUFFER_SIZE} ticks)")
    print(f"Creatures : {', '.join(c.creature_id for c in CREATURES)}")

    with requests.Session() as session:
        session.headers["Content-Type"] = "application/json"
        for profile in CREATURES:
            simulate_creature(profile, session)

    print(f"\n{BOLD}{GREEN}Simulation complete.{RESET}\n")


if __name__ == "__main__":
    main()
