# Queue-empty is not execution-complete (the race I kept re-introducing)

> Source: [ADR-004](../docs/decisions/ADR-004-websocket-nested-plan-execution.md).
> Builds on the watchdog guarantee in
> [ADR-005](../docs/decisions/ADR-005-movement-reliability-watchdog.md) and the
> cadence ownership later refined in
> [ADR-021](../docs/decisions/ADR-021-directive-driven-motor-fsm.md) /
> [ADR-022](../docs/decisions/ADR-022-dispatcher-intent-motor-workers.md).

## The symptom

The cat would get a plan like `[look_around, go_to boat]`, start walking toward
the boat — and *while it was still mid-walk* the backend would already be planning
the next thing. New plans landed on top of a cat that hadn't finished the old one.
The behavior looked jittery and "indecisive," but it wasn't an LLM problem. It was
a **race condition** in who decides the cat is ready for a new thought.

## The two bugs underneath

ADR-004 names them precisely. Both come from the runtime still behaving like
stateless HTTP even after it stopped being stateless HTTP.

### Bug 1: "Queue-empty" was standing in for "execution-complete"

The flow was:

- Backend returns a plan (a list of steps).
- Unity enqueues the list on the blackboard.
- The worker **pops a step when it dispatches it** to Malbers.
- `PeriodicMind` watched the blackboard queue and, once it *looked empty*, sent a
  fresh snapshot to ask for the next plan.

Here's the trap: **a step leaves the queue the moment it's handed to the body —
but the body may still be animating or navigating for several more seconds.** So
"queue is empty" fires *long before* "the cat finished moving." The mind requests
a new plan while the legs are still working.

These are two genuinely different facts:

| Fact | What it actually means |
|------|------------------------|
| Queue is empty | Everything has been *dispatched* |
| Body is idle | Everything has *completed* |

I had been using the first as a proxy for the second. They diverge by exactly the
duration of the slowest physical action — which for a navigating cat is "a long
time."

### Bug 2: completion order wasn't authoritative

Because action reports came back through a *separate* out-of-band channel (see
[note 01](01-long-poll-to-websocket.md)), the backend couldn't reliably order
"this plan finished" against "here's the next snapshot." The `race` edge in the
ADR's own diagram says it out loud: `PeriodicMind may request a new plan` can
interleave with `Body completes later`. For multiple cats it gets strictly worse —
each cat lives an ordered local life, but its reports and snapshots are
independent network calls the backend can observe in the wrong order.

## The fix: make completion the signal, and make Unity the cadence authority

Two changes, both about replacing a proxy with the real signal.

**1. Wait on the body, not the queue.** Unity sends the next tick envelope *only*
when all of these hold:

- no backend request is in flight;
- the local action queue is empty;
- **the body adapter is no longer executing an action/navigation;**
- the previous plan's report has been captured and can ride along on the next
  tick.

The third bullet is the fix for Bug 1 — completion now gates planning, not
dispatch.

**2. Unity owns cadence, explicitly.** The backend *never* asks for a new snapshot
and never plans again until Unity sends the next `tick`. The state machine becomes
honest:

```
ReadyToTick → AwaitingPlan → ExecutingPlan → BodyBusy → PlanComplete → ReadyToTick
                                  ↑______________|  (more steps queued)
```

`PlanComplete` is only reached when the body finishes with no steps left — and
*only then* does the report get enqueued for the next tick. One clear authority,
one ordered channel, no race.

There's a subtle dependency worth calling out: this only works because
[ADR-005](../docs/decisions/ADR-005-movement-reliability-watchdog.md) guarantees
**every** action terminates (see [note 03](03-navigation-deadlock-watchdog.md)).
If "wait for the body to finish" could wait forever, gating planning on body
completion would just convert a race into a deadlock. The two ADRs hold hands:
one makes completion *meaningful*, the other makes completion *inevitable*.

## The transferable lesson

> A queue tells you what's been *handed off*, never what's been *finished*. If you
> gate downstream work on an empty queue, you've quietly assumed dispatch ==
> completion — true only when work is instantaneous.

Any time a producer and a consumer run at different speeds, "the buffer is empty"
is a lie about progress. The honest signal is a *completion event from the thing
doing the slow work* — here, the body adapter reporting it's idle. And when
multiple independent actors each have their own timeline, give each one **a single
ordered channel** and one **explicit cadence authority**, so you never have to
reconstruct an order that the network already scrambled.
