# Developing Notes — War Stories from Building Mewi

Blog-draft notes distilled from the real bugs and design reversals in this
project (the cat agent: Unity body + Python LLM brain over a tick loop). Each
note is a self-contained story: the symptom I saw, why it happened, the fix, and
the transferable lesson. Sources are the ADRs under `docs/decisions/` and the
shipped code — every claim here is traceable back to a decision record.

| # | Note | One-line lesson | Primary sources |
|---|------|-----------------|-----------------|
| 01 | [Long-poll was the wrong transport](01-long-poll-to-websocket.md) | Submit-then-poll HTTP coupled my game loop to LLM latency and split ordering across two channels. | ADR-002 → ADR-004 |
| 02 | [Queue-empty is not execution-complete (the race)](02-queue-empty-is-not-done.md) | "The list is empty" and "the body finished moving" are different facts; treating them as one re-plans on top of a still-moving cat. | ADR-004 |
| 03 | [The deadlock that never errored](03-navigation-deadlock-watchdog.md) | A plan that waits forever for an arrival event that never fires isn't crashed — it's deadlocked. Make every action *terminate*, honestly. | ADR-005 |
| 04 | [Distance is not reachability](04-affordance-distance-vs-navmesh.md) | "4.5m away" told the brain it could reach a target; the NavMesh agent said otherwise. The affordance lied. | ADR-005, ADR-021, jump-through-obstacle proposal |

## The thread connecting all four

They're the same mistake wearing four costumes: **trusting a cheap proxy for the
expensive truth.**

- Poll status instead of *being told* the result (01).
- An empty queue instead of a *completion signal* (02).
- "Started the action" instead of *"the body actually arrived"* (03).
- Euclidean distance instead of a *NavMesh path* (04).

Every fix replaced a proxy with the real signal — and the system got both simpler
and more honest each time.
