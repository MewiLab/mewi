"""
payload_generator.py — LLM-driven TickPayload scenario generator.

Generates a sequence of Unity-compatible tick payloads from a natural-language
scenario description.  The LLM is instructed to produce a coherent narrative:
entities drift closer, mood evolves, hunger increases, etc.

Usage
-----
From backend/:

    uv run python scripts/payload_generator.py

Or import in other scripts:

    from scripts.payload_generator import generate_scenario_ticks

    ticks = generate_scenario_ticks(
        "A cat hiding under a sofa while a vacuum cleaner approaches loudly.",
        count=20,
    )
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

# Allow running directly from backend/
sys.path.insert(0, str(Path(__file__).parents[1]))

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm_provider import create_llm_provider
from app.core.config import get_settings

# Generating 20 ticks is a large output.
# The app default (30 s / 1024 tokens) causes truncated JSON and dropped ticks.
# 20 tick objects × ~200 tokens each ≈ 4 000 tokens minimum.
_GENERATOR_TIMEOUT_S  = 120.0
_GENERATOR_MAX_TOKENS = 4096


def _make_generator_llm():
    """Create an LLM provider with higher timeout and token budget for bulk generation."""
    base = get_settings().llm
    settings = base.model_copy(update={
        "timeout":    _GENERATOR_TIMEOUT_S,
        "max_tokens": _GENERATOR_MAX_TOKENS,
    })
    return create_llm_provider(settings)

# ── Schema description sent to the LLM ───────────────────────────────────────

_TICK_SCHEMA = """
Each tick is a JSON object with EXACTLY these fields (no extras, no omissions):
{
  "requestId":  "<unique UUID string>",
  "self": {
    "location":       {"x": <float>, "y": 0.0, "z": <float>},
    "current_action": "<one of: idle | walk | run | crouch | hide | sniff | groom>"
  },
  "mood": {
    "fear":      <float 0.0–1.0>,
    "trust":     <float 0.0–1.0>,
    "curiosity": <float 0.0–1.0>,
    "social":    <float 0.0–1.0>,
    "energy":    <float 0.0–1.0>
  },
  "health": {"hunger": <float 0.0–1.0>},
  "entities": [
    {
      "id":        "<descriptive string>",
      "tags":      ["<tag>", ...],
      "distance":  <float, metres, must decrease/increase coherently across ticks>,
      "direction": "<north | south | east | west | northeast | northwest | southeast | southwest>"
    }
  ]
}
"""

_SYSTEM_PROMPT = (
    "You are a simulation data generator for a cat AI research project.\n"
    "Your job is to generate a sequence of environment snapshots that form a "
    "coherent, realistic emotional arc over the full tick window.\n\n"
    "Rules:\n"
    "  • requestId must be a unique UUID v4 string for every tick.\n"
    "  • Mood values evolve smoothly — max ±0.15 change per tick EXCEPT during a "
    "sudden-stimulus event (e.g., a loud noise, unexpected threat) where a single-tick "
    "jump of up to ±0.30 is allowed for at most 2 consecutive ticks.\n"
    "  • The mood arc must be DISTINCT and clearly reflect the scenario's emotional journey: "
    "track gradual rises, peaks, and declines rather than hovering at flat values.\n"
    "  • Entity distances must change consistently with the scenario narrative.\n"
    "  • The cat's position (x, z) should drift plausibly with its current_action.\n"
    "  • hunger increases slowly over time (max +0.05 per tick).\n"
    "  • Return ONLY a valid JSON array — no markdown fences, no explanation.\n\n"
    f"TICK SCHEMA:\n{_TICK_SCHEMA}"
)


# ── Public API ────────────────────────────────────────────────────────────────

_BATCH_SIZE = 10   # ticks per LLM call — keeps output well within token limits


def generate_scenario_ticks(
    scenario_description: str,
    count: int = 20,
    *,
    fallback_on_error: bool = True,
) -> list[dict[str, Any]]:
    """
    Generate `count` tick payloads by splitting the work into batches of
    _BATCH_SIZE LLM calls and concatenating the results.

    Batching avoids the JSON-truncation issue that occurs when a single call
    tries to produce ~5 000 tokens (20 ticks × ~275 tokens each), which
    exceeds the model's practical output ceiling even at max_tokens=4096.

    Args:
        scenario_description: Natural-language description of the scenario.
        count: Total number of ticks to generate (default 20).
        fallback_on_error: When True, bad batches are padded with sinusoidal
            stubs so the simulation script can always complete.
    """
    llm   = _make_generator_llm()
    ticks: list[dict[str, Any]] = []
    batch = 0

    while len(ticks) < count:
        remaining  = count - len(ticks)
        batch_size = min(_BATCH_SIZE, remaining)
        batch     += 1

        continuation = (
            ""
            if not ticks
            else (
                f"\nContinue from tick {len(ticks) + 1}. "
                f"The last tick ended with: "
                f"fear={ticks[-1].get('mood', {}).get('fear', '?')}, "
                f"entities at distance="
                f"{[e.get('distance') for e in ticks[-1].get('entities', [])]}. "
                "Maintain narrative continuity."
            )
        )

        user_prompt = (
            f"Scenario: {scenario_description}{continuation}\n\n"
            f"Generate exactly {batch_size} ticks as a JSON array "
            f"(ticks {len(ticks) + 1}–{len(ticks) + batch_size} of {count}).\n"
            "The sequence must show clear progression within this window.\n"
            "Return ONLY the JSON array."
        )

        print(f"  [generator] Batch {batch}: requesting ticks "
              f"{len(ticks) + 1}–{len(ticks) + batch_size} …")

        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])

        raw_text = response.content.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            batch_ticks = json.loads(raw_text)
            if not isinstance(batch_ticks, list):
                raise ValueError(f"expected list, got {type(batch_ticks).__name__}")
        except (json.JSONDecodeError, ValueError) as exc:
            if not fallback_on_error:
                raise RuntimeError(
                    f"LLM batch {batch} returned invalid output: {exc}"
                ) from exc
            print(f"  [generator] WARNING: batch {batch} failed ({exc}). "
                  f"Padding {batch_size} tick(s) with fallback stubs.")
            batch_ticks = _sinusoidal_fallback(batch_size)

        ticks.extend(batch_ticks[:batch_size])

    # Ensure every tick has a unique requestId (guard against LLM reusing IDs)
    seen: set[str] = set()
    for tick in ticks:
        rid = tick.get("requestId", "")
        if not rid or rid in seen:
            tick["requestId"] = str(uuid.uuid4())
        seen.add(tick["requestId"])

    print(f"  [generator] Done — {len(ticks)} ticks ready.")

    return ticks


# ── Sinusoidal fallback (no LLM required) ────────────────────────────────────

def _sinusoidal_fallback(count: int, arc: str = "neutral") -> list[dict[str, Any]]:
    """
    Deterministic stub ticks used when the LLM call fails or --mode=fallback.

    arc="happy"    — models cat_01's playful, positive emotional journey.
    arc="stressed" — models cat_02's fear-spike-then-sadness journey.
    arc="neutral"  — generic sinusoidal baseline (backwards-compatible default).

    Each arc is scaled to `count` ticks so the full emotional journey is visible
    regardless of whether count=10 or count=50.
    """
    import math

    ticks = []
    for i in range(1, count + 1):
        t = i / count  # normalised progress 0 → 1

        if arc == "happy":
            # Curiosity and energy peak during mid-play then settle.
            # Bell-curve playfulness peaking around 55 % of the run.
            play = math.sin(math.pi * min(t / 0.7, 1.0))

            fear      = round(max(0.02, 0.30 - 0.22 * t + 0.03 * math.sin(i * 0.7)), 3)
            trust     = round(min(0.88, 0.50 + 0.35 * t + 0.03 * math.sin(i * 0.4)), 3)
            curiosity = round(min(0.95, 0.45 + 0.50 * play  + 0.03 * math.sin(i * 0.5)), 3)
            social    = round(min(0.90, 0.30 + 0.55 * t     + 0.03 * math.sin(i * 0.3)), 3)
            energy    = round(min(0.95, 0.45 + 0.45 * play  + 0.03 * math.cos(i * 0.4)), 3)
            hunger    = round(min(0.50, 0.05 + 0.45 * t), 3)

            # Action tracks the play arc.
            if t < 0.15:
                action = "idle"
            elif t < 0.25:
                action = "sniff"
            elif t < 0.65:
                action = "walk" if play < 0.7 else "run"
            elif t < 0.85:
                action = "walk"
            else:
                action = "groom"

            loc_x = round(3.0 + 1.5 * math.sin(i * 0.30), 3)
            loc_z = round(2.0 + 1.5 * math.cos(i * 0.25), 3)

            entities = [
                {
                    "id": "feather_wand",
                    "tags": ["toy", "interactive"],
                    "distance": round(max(0.3, 2.5 - 2.0 * play + 0.2 * math.sin(i * 0.5)), 2),
                    "direction": "south",
                }
            ]

        elif arc == "stressed":
            # Sharp sigmoid fear-spike at ~10 % of the run, then slow sad decay.
            spike = 1.0 / (1.0 + math.exp(-12.0 * (t - 0.10)))  # 0 → 1 fast at t=0.10
            linger = max(0.0, 1.0 - max(0.0, t - 0.20) * 1.1)   # decays after 20 %

            fear      = round(min(0.97, 0.20 + 0.77 * spike * (0.35 + 0.65 * linger)
                                  + 0.02 * math.sin(i * 0.5)), 3)
            trust     = round(max(0.03, 0.50 - 0.47 * spike + 0.02 * math.sin(i * 0.4)), 3)
            curiosity = round(max(0.03, 0.50 - 0.45 * spike + 0.02 * math.sin(i * 0.3)), 3)
            social    = round(max(0.02, 0.30 - 0.28 * spike), 3)
            energy    = round(max(0.08, 0.70 - 0.58 * t + 0.02 * math.sin(i * 0.5)), 3)
            hunger    = round(min(0.80, 0.05 + 0.75 * t), 3)

            # Flee first, then freeze/hide.
            if t < 0.08:
                action = "idle"
            elif t < 0.18:
                action = "run"
            else:
                action = "hide" if fear > 0.55 else "crouch"

            # Barely moves after fleeing to hiding spot.
            loc_x = round(1.5 + 0.15 * math.sin(i * 0.12), 3)
            loc_z = round(0.8 + 0.12 * math.cos(i * 0.10), 3)

            alarm_dist = round(max(1.0, 8.0 - 6.0 * spike), 2)
            entities = [
                {
                    "id": "car_alarm_source",
                    "tags": ["loud", "unknown", "threat"],
                    "distance": alarm_dist,
                    "direction": "north",
                }
            ]

        else:  # "neutral" — original generic baseline
            fear      = round(min(1.0, 0.30 + i * 0.02), 3)
            trust     = round(max(0.0, 0.50 - i * 0.01), 3)
            curiosity = 0.5
            social    = 0.2
            energy    = round(max(0.0, 1.0 - i * 0.01), 3)
            hunger    = round(min(1.0, i * 0.04), 3)
            action    = "idle"
            loc_x     = round(2.0 + math.sin(i * 0.4) * 0.3, 3)
            loc_z     = round(1.5 + math.cos(i * 0.3) * 0.25, 3)
            entities  = []

        ticks.append({
            "requestId": str(uuid.uuid4()),
            "self": {
                "location": {"x": loc_x, "y": 0.0, "z": loc_z},
                "current_action": action,
            },
            "mood": {
                "fear":      fear,
                "trust":     trust,
                "curiosity": curiosity,
                "social":    social,
                "energy":    energy,
            },
            "health": {"hunger": hunger},
            "entities": entities,
        })

    return ticks


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint

    demo_scenario = (
        "A highly anxious cat is hiding behind a sofa. "
        "A loud vacuum cleaner is approaching from the north, getting closer each tick. "
        "The cat's fear rises as it gets closer and it eventually flees south."
    )

    print(f"\nScenario: {demo_scenario}\n")
    result = generate_scenario_ticks(demo_scenario, count=5)
    print("\nFirst 5 generated ticks:\n")
    pprint.pprint(result, width=100)
