# Long-poll was the wrong transport for a game tick

> Sources: [ADR-002](../docs/decisions/ADR-002-unity-backend-tick-protocol.md)
> (the submit-then-poll design), superseded by
> [ADR-004](../docs/decisions/ADR-004-websocket-nested-plan-execution.md).

## The setup

The cat's next action comes from an LLM-backed behavior graph. LLM latency is
wildly variable — hundreds of milliseconds to several seconds depending on the
provider and model. Unity, meanwhile, wants a decision on every game tick.

My first transport was the textbook "don't block on a slow backend" answer:
**submit-then-poll**, backed by a Redis job queue.

1. Unity `POST`s a tick → backend enqueues a job in Redis, returns `202 Accepted`
   with a `job_id` immediately.
2. A background worker `BLPOP`s the queue, runs the graph, writes the result back
   under the same `job_id`.
3. Unity polls `GET /tick/jobs/{job_id}` until `status` is `done` or `error`,
   then applies the action.

On paper this is correct, and ADR-002 still lists its genuine wins: the POST is
constant-time so Unity never blocks on the LLM, the worker scales independently,
and Redis-backed state survives a process restart.

## Why it was still the wrong call

The problem wasn't throughput — it was that **the transport told me nothing about
ordering**, and a living agent is all about ordering.

Two things went wrong in practice:

- **Polling is busywork that still doesn't decouple cadence.** Unity had to
  implement the `queued → processing → done` state machine and keep hammering
  `GET` until a terminal state. The round-trips were tolerable, but the client
  now owned latency-handling logic that had nothing to do with being a cat.
- **The real killer: reports came back out-of-band.** Action results ("this plan
  finished, here's what happened to each step") were a *separate* HTTP callback,
  independent from the snapshot tick that asked for the next plan. With one cat
  it was tolerable. With multiple cats — each living an ordered local life but
  emitting reports and snapshots as independent network calls — **the backend
  could observe events in a different order than the cat actually lived them.**
  Two stateless request streams have no shared clock.

That's the deeper lesson. HTTP submit-poll gave me *delivery* but not *sequence*.
For an agent loop, sequence **is** the product. "What just happened" and "what
should happen next" have to arrive as one ordered story, or the brain plans on
top of a world it has misread.

## The fix: one WebSocket per cat, nested envelopes

ADR-004 replaced the whole thing with a single per-creature WebSocket as the only
runtime control channel. The move that mattered: Unity sends a **nested `tick`
envelope** carrying both halves of the loop together:

```json
{
  "type": "tick",
  "report": { "...": "result of the PREVIOUS plan, step by step" },
  "snapshot": { "...": "what the world looks like RIGHT NOW" }
}
```

One connection per cat gives ordered messages for that cat for free. The backend
now sees "what happened" and "what the world looks like now" as a single ordered
message — no cross-channel race to reconcile. HTTP action reporting didn't get
patched; it got **removed from the runtime loop entirely** (it can live on as a
debug API, but it must never be load-bearing for planning order).

## The transferable lesson

> When you reach for "async job + poll," ask whether you actually need
> *throughput* or whether you need *ordering*. Polling buys the first and silently
> denies the second.

Submit-then-poll is the right reflex for fire-and-forget batch work where each
job is independent. It is the *wrong* reflex the moment results must be sequenced
against new requests — because you've split one causal story across two stateless
channels, and nothing puts it back together. A stateful, ordered channel (a
WebSocket, an actor mailbox, a single queue) isn't a performance upgrade there;
it's a *correctness* upgrade.

And notice the irony worth a paragraph in the post: the "simpler" HTTP design
needed *more* client code (a polling state machine + an out-of-band report path),
while the "heavier" WebSocket design **deleted** code. Choosing the transport that
matches the problem's shape usually subtracts complexity rather than adding it.
