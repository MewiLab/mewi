# The deadlock that never threw an error

> Source: [ADR-005](../docs/decisions/ADR-005-movement-reliability-watchdog.md)
> and the verification checklist in
> [docs/current_need_to_fix.md](../docs/current_need_to_fix.md).

## The symptom

`go_to → eat` would sometimes just... stop. The cat walked toward a fish, got
nudged against an obstacle, and froze. No exception, no error log, no crash. The
worker sat there reporting `bodyBusy=True` forever, the plan never advanced to
`eat`, and the next tick never fired. The whole agent was wedged, and from the
outside it looked *alive but catatonic*.

This is the worst class of bug: a **silent deadlock**. Nothing failed. Everything
was patiently waiting for an event that was never going to come.

## Why it happened

The cat's body is moved by Malbers + Unity's `NavMeshAgent`, not by my own
controller. The worker dispatches `go_to` and then waits for Malbers/NavMesh to
raise an **arrival event**. `IsBusy` correctly stayed true during navigation,
action execution, and cooldown — so far so good.

But there's no contract that an arrival event *will* fire. If the agent gets stuck
on geometry and stops making progress, NavMesh never declares "arrived," Malbers
never ends the mode, `IsBusy` never flips, and the worker waits indefinitely. The
plan can't terminate, so — by the cadence rule from
[note 02](02-queue-empty-is-not-done.md) — no new plan is ever requested.

The root cause is an **unfalsifiable success condition**. The only way out of the
wait state was "arrived," and there was no path that said "we are never going to
arrive, give up gracefully."

## The decision: reliability beats naturalism (for a prototype)

The explicit call in ADR-005: when the cat is stuck, briefly try to fix it, then
**warp/teleport** it to the destination so the rest of the plan continues. A
teleporting cat is ugly; a frozen cat is broken. For a prototype, *every plan must
terminate* — that guarantee is load-bearing for the entire backend, which is
allowed to fire-and-forget precisely because the body always finishes
(see [ADR-018](../docs/decisions/ADR-018-proposal-arbiter-tick-graph.md)).

## The fix: a self-recovering navigation watchdog

A small pure-C# state machine that watches progress, not just arrival:

```
Idle → Navigating → Repathing → Warping → (Arrived | WarpedToNavMesh | WarpedRaw)
```

The pieces that made it robust:

1. **Redefine "progress" as "closer to the destination," not "moved somewhere."**
   This was the single most important line in the whole fix
   (`docs/current_need_to_fix.md`, first bullet). A cat scrabbling against a wall
   *is moving* — it's just not getting anywhere. Measuring distance-to-goal, not
   displacement, is what lets the watchdog tell "making progress" from "thrashing."
2. **Escalate, don't jump straight to the hammer.** Stalled past
   `repathDelaySeconds` → try a **repath** (up to `maxRepathAttempts`). Only when
   repaths are exhausted *or* `hardTimeoutSeconds` trips → **warp**. The warp
   itself degrades: NavMesh-projected if there's mesh within
   `warpNavMeshSampleRadius`, raw transform move as the final fallback.
3. **Keep the watchdog pure; keep side effects in the adapter.** `NavigationWatchdog`
   makes *zero* Malbers/NavMesh calls — it's pure timing/distance state, so it's
   unit-testable and literally *cannot itself break navigation*. The adapter owns
   every actual warp/repath side effect. (Same pattern for `ActionWatchdog`, which
   lets `eat`/`sit`/`sleep` animations finish naturally but forces cleanup if the
   mode never starts or never ends.)
4. **Record *why* it completed, honestly.** Every termination carries a reason —
   `Arrived`, `ArrivedAfterRepath`, `WarpedToNavMesh`, `WarpedRaw`, `Failed` — into
   the plan-step report. The backend gets the truth ("we had to warp here"), not a
   blanket "completed" that hides the struggle. That honest reason becomes
   structured evidence the backend can learn from later.

It piggybacks on the existing per-frame `OnPreInput` hook — no new `Update()`, no
protocol change (the report's `reason` field was already free-form text). The
recovery cost almost nothing to bolt on because it reused seams that already
existed.

## A second-order trap I want to remember

The reason warping is even *safe* to do bluntly is that a separate fix made the
**target position** trustworthy: `go_to` now aims at the perceived snapshot
position, then `SmartObject.perceptionCenter`, rather than some authored point
that might sit far from the interactable surface. A reliability fallback is only
as good as the coordinate you're falling back *to* — warp the cat to a bad target
and you've just teleported it into a wall. (This is the seam where the affordance
bug in [note 04](04-affordance-distance-vs-navmesh.md) lives.)

## The transferable lesson

> If a wait state can only be exited by a success event, and nothing guarantees
> that event fires, you don't have a happy path — you have a deadlock waiting for
> the wrong input.

Every "wait until done" needs a **timeout and an escape hatch**, and the escape
has to be *something the system can always do by itself* (here: warp). Also:
when you're detecting "stuck," measure progress toward the goal, not mere
activity — thrashing looks busy. And keep the *decision* logic pure and the
*effects* at the edge, so your safety mechanism is testable and can't become the
thing that breaks you. Finally, when you take a shortcut for reliability, **record
that you took it** — an honest `WarpedRaw` in the logs is worth ten silent
"completed"s.
