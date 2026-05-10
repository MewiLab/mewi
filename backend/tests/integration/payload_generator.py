"""
payload_generator.py — LLM-driven TickPayload scenario generator.

Generates a sequence of Unity-compatible tick payloads from a natural-language
scenario description.  The LLM is instructed to produce a coherent narrative:
entities drift closer, mood evolves, hunger increases, etc.

Usage
-----
From backend/:

    uv run python tests/integration/payload_generator.py

Or import in other test scripts:

    from tests.integration.payload_generator import generate_scenario_ticks

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

# Allow `uv run python tests/integration/payload_generator.py` from backend/
sys.path.insert(0, str(Path(__file__).parents[2]))

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
    "coherent, realistic story.\n\n"
    "Rules:\n"
    "  • requestId must be a unique UUID v4 string for every tick.\n"
    "  • Mood values must evolve smoothly — no sudden jumps larger than 0.15 between ticks.\n"
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

def _sinusoidal_fallback(count: int) -> list[dict[str, Any]]:
    """Deterministic stub used when the LLM call fails."""
    import math

    ticks = []
    for i in range(1, count + 1):
        ticks.append({
            "requestId": str(uuid.uuid4()),
            "self": {
                "location": {
                    "x": round(2.0 + math.sin(i * 0.4) * 0.3, 3),
                    "y": 0.0,
                    "z": round(1.5 + math.cos(i * 0.3) * 0.25, 3),
                },
                "current_action": "idle",
            },
            "mood": {
                "fear":      round(min(1.0, 0.3 + i * 0.02), 3),
                "trust":     round(max(0.0, 0.5 - i * 0.01), 3),
                "curiosity": 0.5,
                "social":    0.2,
                "energy":    round(max(0.0, 1.0 - i * 0.01), 3),
            },
            "health": {"hunger": round(min(1.0, i * 0.04), 3)},
            "entities": [],
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
