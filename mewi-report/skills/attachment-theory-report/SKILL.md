---
name: attachment-theory-report
description: Analyze Mewi behavioral report data as an attachment-theory style interaction pattern. Use when assigning or explaining secure, anxious-preoccupied, dismissive-avoidant, or fearful-avoidant leaning from cat-session traces, trust arcs, attachment metrics, and key moments.
---

# Attachment Theory Report Analysis

Use this skill to turn a Mewi report trace into a concise attachment-theory interpretation. This is a behavioral reading of game interactions, not a clinical diagnosis.

## Inputs

Read all available report content before labeling:

- `summary`: trust gain, primary bond, latency, patience.
- `attachment_profile`: patience, approach-retreat oscillation, offering, dwell, persistence after avoidance, selectivity.
- `cats.*.trust_arc`: trust gains, dips, repair, final state.
- `cats.*.moments` and `timeline`: rupture, repair, avoidance, pursuit, and comfort moments.
- `attention_pct` and encounter logs: whether attention is flexible or rigidly focused.

## Classification Heuristics

Prefer a "leaning" label unless the evidence is very strong.

- **Secure-leaning**: high patience under rejection, high dwell without forcing action, low pursuit after avoidance, steady repair after dips, flexible attention to more than one cat.
- **Anxious-preoccupied leaning**: repeated pursuit after avoidance, high call/chase/pet attempts, difficulty letting distance remain, strong approach-retreat oscillation around rejection.
- **Dismissive-avoidant leaning**: low bids for contact, low dwell, quick retreat, limited repair attempts, low affective investment after non-response.
- **Fearful-avoidant leaning**: high desire for closeness paired with sharp retreats, volatile trust arcs, repeated rupture without stable repair, mixed approach and avoidance.

For this project, useful score proxies are:

```text
secure = avg(patience, low_oscillation, offer_without_demand, dwell_without_action)
anxious = avg(persistence_after_avoidance, 100 - low_oscillation, 100 - patience)
avoidant = avg(100 - offer_without_demand, 100 - dwell_without_action, selectivity)
fearful_avoidant = avg(100 - low_oscillation, 100 - patience, selectivity)
```

## Explanation Pattern

Return:

1. `type`: the attachment-theory label.
2. `modifier`: a short behavioral flavor, such as "patient, selective attunement."
3. `summary`: 1-2 sentences explaining the dominant pattern.
4. `evidence`: 3-4 concrete evidence cards tied to numbers and session events.
5. `scores`: comparative scores if available.
6. `caveat`: "This is a behavioral reading of a game trace, not a clinical diagnosis."

## Tone

Be clear and grounded. Do not over-pathologize. Avoid claiming the user's real-life attachment style. Say "your trace reads as" or "this interaction pattern leans toward" rather than "you are."

Keep the existing narrative archetype if present; add the attachment-theory interpretation as the default analytical layer and leave the archetype as a secondary view.
