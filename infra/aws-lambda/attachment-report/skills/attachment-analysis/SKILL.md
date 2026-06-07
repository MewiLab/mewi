---
name: attachment-analysis
description: Run an end-to-end attachment-style analysis of a Mewi player from their session traces, producing the processed_data `attachment_analysis` block. Use when an agent (Claude Agent SDK) must read raw/processed report data for a user, derive Strange-Situation behavioral signals, score the four attachment leanings, and write a grounded, non-clinical interpretation. Complements (does not replace) the `attachment-theory-report` skill.
---

# Attachment Analysis (agent-driven)

This skill lets an agent take a Mewi player's interaction traces and produce the
`attachment_analysis` object that the report site renders. It is a **behavioral
reading of a game trace, not a clinical diagnosis**.

It is grounded in [ADR-007](../../../../../../docs/decisions/ADR-007-attachment-signature-pipeline.md):
the cat's assigned profile is the *controlled stimulus*; the only thing we infer
is the *player's* response pattern. Carry that honesty through every output.

> Relationship to the existing skill: `attachment-theory-report` holds the
> conceptual heuristics and classification language. This skill adds the
> concrete data-location, signal-derivation, and output-contract steps an agent
> needs to actually run. When both apply, read both; prefer this one for the
> procedure and the JSON shape.

## When to use

- You are asked to analyze, (re)generate, or explain a user's attachment leaning.
- You have a `report_slug` (e.g. `vanillasky_01`) and need to fill or update the
  `attachment_analysis` field in `pipeline/processed_data/report_<slug>.json`.

## Inputs — where the data actually lives

Resolve the slug from `pipeline/user_info.json` (`users.<id>.report_slug`), then
read in this priority order:

1. **Raw sessions** — `pipeline/raw_data/sessions/<slug>/*.json` (richest).
   Each file: `{schema_version, user_id, source, session}` where `session` has:
   - `session_index`, `duration_seconds`
   - `events[]`: `{t, actor, action, params}` — `actor` is `human` | `cat`;
     `action` ∈ approach / retreat / offer / call / pet / wait / withdrew / …
   - `multi_cat_encounters[]`: `{t, cats_present[], human_action, outcome}`
2. **Processed report** — `pipeline/processed_data/report_<slug>.json`. Use when
   raw is unavailable, or to cross-check. Relevant fields:
   - `summary`: `avg_trust_gained`, `primary_bond`, `avg_reaction_latency_s`,
     `patience_pct`
   - `attachment_profile[]`: `{label, value (0–100), color}` — the six derived
     signals (see mapping below)
   - `cats.<id>.trust_arc[]` (one int per session, can dip), `cats.<id>.moments[]`
   - `radar` (Approach/Retreat/Offer/Wait/Call/Pet), `attention_pct`
3. **Overrides** — `pipeline/report_overrides/<slug>.json`. If an
   `attachment_analysis` is present here, it is human-authored ground truth:
   refine around it, do not contradict it silently.

Read everything available before labeling. Never invent sessions or numbers.

## Step 1 — Derive Strange-Situation signals

Map raw events to the ADR-007 behavioral constructs (these are the dependent
variable — the player's response to cat-initiated / episode events, not generic
activity):

| Construct (ADR-007) | Derive from |
|---|---|
| `reapproach_latency` | time from a `cat withdrew` event to the next `human approach` |
| `pursuit_ratio` | human approaches *after* a withdrawal ÷ withdrawals |
| `time_near_ratio` | share of session within close distance (`params.distance_final_m`) |
| `reunion_response` | approach/closeness after a return-after-absence |
| `withdrawal_tolerance` | time the human lets distance stand before acting |
| selectivity | spread of `attention_pct` / distinct primary bond vs. others |

If you only have processed data, the six `attachment_profile` labels already
encode these — use them directly:

- Patience under rejection ↔ withdrawal_tolerance (high = secure)
- Low approach-retreat oscillation ↔ inverse pursuit volatility
- Offer without demanding return ↔ secure offering
- Zone-dwell without action ↔ tolerance of distance
- Persistence after avoidance ↔ pursuit_ratio (high = anxious)
- Selectivity across cats ↔ selectivity

## Step 2 — Score the four leanings (0–100)

Use these transparent proxies (same spirit as `attachment-theory-report`; values
are the 0–100 `attachment_profile` signals). Keep them inspectable — a professor
should be able to follow them:

```text
secure          = avg(patience, low_oscillation, offer_without_demand, dwell_without_action)
anxious          = avg(persistence_after_avoidance, 100 - low_oscillation, 100 - patience)
avoidant         = avg(100 - offer_without_demand, 100 - dwell_without_action, selectivity)
fearful_avoidant = avg(100 - low_oscillation, 100 - patience, selectivity)
```

Pick the **top** score as the leaning. If the top two are within ~8 points, say
"mixed / leaning" and lower the confidence.

## Step 3 — Classification heuristics

Prefer a **"-leaning"** label unless evidence is strong.

- **Secure-leaning**: high patience under rejection, high dwell without forcing,
  low pursuit after avoidance, steady repair after trust dips, flexible attention.
- **Anxious-preoccupied leaning**: repeated pursuit after avoidance, high
  call/chase/pet attempts, can't let distance remain, strong oscillation.
- **Dismissive-avoidant leaning**: few contact bids, low dwell, quick retreat,
  limited repair, low investment after non-response.
- **Fearful-avoidant leaning**: wants closeness but retreats sharply, volatile
  trust arcs, rupture without stable repair, mixed approach/avoidance.

## Step 4 — Confidence

- `low` — < 3 sessions, sparse events, or top scores within ~8 points.
- `Moderate` — 3–5 coherent sessions with a clear top leaning (default for the
  current prototype dataset).
- Never claim `high`. The estimate is an unvalidated research signal until
  checked against a self-report instrument (e.g. ECR-R), per ADR-007.

## Step 5 — Output contract

Write/return exactly this shape (it matches the existing `attachment_analysis`
block in `processed_data`):

```jsonc
{
  "type": "Secure-leaning attachment",
  "modifier": "patient, selective attunement",        // short behavioral flavor
  "summary": "Your trace reads closest to ...",       // 1–2 sentences, "your trace reads as"
  "evidence": [                                        // 3–4 cards, each tied to a number + event
    { "label": "Secure-base signal", "detail": "Patience under rejection is 74% ..." }
  ],
  "scores": { "secure": 67, "anxious": 29, "avoidant": 47, "fearful_avoidant": 43 },
  "confidence": "Moderate",
  "caveat": "This is a behavioral reading of a five-session game trace, not a clinical diagnosis."
}
```

Then place it under the top-level `attachment_analysis` key of
`pipeline/processed_data/report_<slug>.json`. Do not hand-edit other pipeline
outputs — if upstream signals change, they come from `process.py`.

## Tone & guardrails

- Be clear and grounded; do not over-pathologize.
- Say "your trace reads as" / "this interaction pattern leans toward" — never
  "you are." Do not claim the player's real-life attachment style.
- Every evidence card must cite a concrete number or session event from the data
  you read. No evidence → lower confidence, not invented support.
- Keep any existing narrative archetype (`cats.*.archetype`) as a secondary view;
  the attachment reading is the default analytical layer, not a replacement.
- Honor the controlled-stimulus framing: the cat's assigned type is the
  condition, not a finding about the cat.

## Quick self-check before returning

- [ ] Resolved the slug and read raw sessions (or stated why only processed).
- [ ] Scores computed from real signals, top leaning chosen, ties → lower confidence.
- [ ] 3–4 evidence cards, each with a number/event.
- [ ] Output matches the JSON contract; confidence ≤ Moderate.
- [ ] No clinical/"you are" language; archetype preserved as secondary.
