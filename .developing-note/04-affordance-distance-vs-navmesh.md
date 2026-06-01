# Distance is not reachability (the affordance that lied)

> Sources: [docs/jump_through_obstacle_proposol.md](../docs/jump_through_obstacle_proposol.md),
> [ADR-005](../docs/decisions/ADR-005-movement-reliability-watchdog.md),
> [ADR-021](../docs/decisions/ADR-021-directive-driven-motor-fsm.md) (target
> resolvability), and the affordance builder in
> [app/agent/mind/affordances.py](../mewi-backend/app/agent/mind/affordances.py).

## The symptom

The brain kept choosing targets it couldn't actually get to. The LLM would pick
`go_to SM_Fish_1` because the perception said the fish was *right there* — "4.5m,
north-east" — and then the cat would grind against a fence, a ledge, or a gap it
had no path across. The intent was reasonable given the information the brain had.
**The information was wrong.**

## Why it happened: I let the perception layer reason in straight lines

Look at how the scene gets described to the brain. In
[semantic_service.py](../mewi-backend/app/services/perception/semantic_service.py)
the cat's sense of "can I get to this?" is built from **Euclidean distance**:

```python
if distance <= 1.8:   # "right next to"
elif distance <= 4.5: # "a few steps away"
elif distance <= 8.0: # "nearby"
```

Those `nearness` phrases feed the affordance list — the menu of "things you could
go interact with" that the arbiter chooses from. The trouble is that distance is
*as the crow flies*, and **a cat is not a crow.** A fish 4.5m away through a wall
is, for navigation purposes, infinitely far. But the affordance presented it as
"a few steps away," so the brain treated it as reachable and committed to it.

The affordance was a **proxy** (distance) standing in for the **truth** (is there
a NavMesh path?). They agree in open space and diverge exactly where the level
geometry gets interesting — which is everywhere worth playing in.

## Two layers, two different owners

The jump-through-obstacle analysis names the boundary cleanly, and it's the heart
of the fix:

- **NavMesh decides whether a route *exists*.** Reachability is a pathfinding
  question, full stop. Distance can *hint* at it but can never *answer* it.
- **Malbers decides how to *animate* a special traversal** (jump a gap, climb a
  ledge, drop down) once the NavMesh route says one is needed.
- **The adapter supervises reliability** and reports honest completion.
- **Triggers / distance provide local context, not the movement brain.**

The seductive wrong fix (a friend's suggestion in the proposal doc) was to bolt
trigger colliders on stairs that force a Malbers jump state. The proposal shoots
it down for the right reason: if the trigger animates the body forward while the
`NavMeshAgent` still thinks it's blocked, **the animation and the pathfinder fight
each other** — snapping, stuck movement, repeated recovery warps. You can't fix a
reachability lie by making the body lie back. The route has to actually exist on
the mesh (author a `NavMeshLink`/`OffMeshLink`), and *then* let Malbers handle the
jump. Distance triggers are demoted to hints and safety metadata.

## How the codebase moved toward truth

The fix isn't a single commit; it's a direction the affordance layer grew in:

1. **Reachability comes from route status, not distance.**
   `affordances.py::_targets_from_reachable_routes` builds explore targets from
   `place_context.reachable_zone_ids` and `navigation_context.zone_routes`, and
   **explicitly drops anything whose route `status == "blocked"`**. That's the
   real signal — "the navigation layer says you can get there" — replacing
   "it's geometrically close."
2. **The body is the backstop, not the source of truth.** Per
   [ADR-005](../docs/decisions/ADR-005-movement-reliability-watchdog.md), even if a
   not-actually-reachable target slips through, the watchdog repaths-then-warps so
   the plan still terminates (see [note 03](03-navigation-deadlock-watchdog.md)).
   Reliability covers the gap while the perception layer gets more honest — but a
   warp is a *patch over* a bad affordance, not a substitute for a good one.
3. **A target is only valid if it resolves to something the body can aim at.**
   [ADR-021](../docs/decisions/ADR-021-directive-driven-motor-fsm.md) surfaces the
   matching half on the Unity side: a directive target like `mewi_cat` must
   resolve to an actual `Transform` or the `go_to` is rejected. "Named in the
   prompt" and "addressable in the world" are, once again, two different facts.

## The transferable lesson

> Proximity is not accessibility. The cheap geometric proxy (distance) and the
> expensive structural truth (a path exists) agree exactly where it doesn't
> matter — open ground — and disagree exactly where it does — walls, ledges, gaps.

When you hand an agent a menu of choices, every item on that menu is an implicit
promise: *"you can actually do this."* If the menu is built from a proxy that the
executor doesn't share, the agent will keep making locally-sensible decisions that
are globally impossible, and you'll blame the planner for what is really a
perception bug. Build affordances from the **same source of truth the executor
uses** — here, the NavMesh — and keep distance for what it's honestly good at:
flavor text ("a few steps away"), priority hints, and safety triggers. Never let
it answer a question it can't actually answer.
