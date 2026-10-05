# LLM Directive, Weighted FSM, And Affordance Plan

## Short Version

Your instinct is right: the cat should stay alive and busy on the Unity side,
while the LLM steers intent at a slower, higher level.

The strongest design is a hybrid:

- Unity owns moment-to-moment action choice, reachability, animation timing,
  safety, interruption, and retries.
- The LLM owns high-level desire: "investigate the fish crate", "stay near the
  player", "rest in a safe place", "avoid the noisy area".
- The LLM should bias a local behavior policy through weights, focus targets,
  and optional short plan sketches, but it should not be the only decision node
  every 2-3 seconds.
- Actions should become affordance-based so Unity can tell the LLM what is
  actually reachable and doable before the LLM proposes intent.

In other words: the LLM should be the cat's slow mind. Unity should be the body,
reflexes, local planner, and behavior loop.

## Current Code Fit

The current code already leans toward this architecture:

- `CreatureBlackboard` has `MindWeights`, `MindFocusTarget`,
  `SetMindWeights(...)`, and a queue for explicit `IntentMessage` plans.
- `CatBehaviorFSM` already models behavior as weighted nodes such as `Explore`,
  `Investigate`, `SeekFood`, `Socialize`, `Rest`, `Safety`, and `Groom`.
- `MindTicker` enables directive mode and sends snapshots periodically while the
  cat keeps moving locally.
- `AgentNetworkManager` already parses both legacy `plan_steps` and a separate
  high-level `intent` field.
- `CreatureWorker` remains the single path from intent strings to
  `MotorCommand` and Malbers execution.

That is a good foundation. The missing piece is not "more LLM control"; it is a
clean affordance contract between world state, local FSM choice, and LLM
directive updates.

## Critique Of Option A: Let The LLM Modify Graph Weights

This is the best first step because it keeps the cat busy without requiring the
LLM to micromanage every body action.

### What Works

- The cat can keep moving while the backend is thinking or delayed.
- Local mood, health, fear, hunger, perception, and animation state can affect
  behavior instantly.
- The LLM can nudge broad style instead of issuing brittle low-level commands.
- Weight changes are compact to send over the network.
- The system degrades gracefully: if no LLM response arrives, default weights
  still produce behavior.

### Main Risk

Weights alone are too abstract. If the LLM says "seek food" but Unity has no
reachable edible affordance, the FSM may wander, smell, or retry in a way that
looks confused. The system needs action availability, target reachability, and
failure reasons to shape the local choice.

### Guardrails Needed

- Clamp LLM-authored weights to a designer-approved range.
- Smooth weight changes over time so the cat does not flip personality every
  tick.
- Add a TTL so old LLM intent decays back toward local defaults.
- Keep safety, physics, and animation feasibility local and non-negotiable.
- Treat the LLM's focus target as a bias, not a command.
- Log the final score table so debugging answers "why did the cat do that?"

## Critique Of Option B: Make Actions Affordance-Based And FSM-Complete

This is the direction I would take next.

An affordance-based FSM means Unity first asks, "What can the cat actually do
from here?" Then the behavior policy chooses among valid options. The LLM sees a
compact summary of those affordances and sends a high-level goal or a short
plan sketch.

### What Works

- The LLM stops inventing impossible actions.
- Unity can reject unreachable targets before they become plans.
- The snapshot becomes more useful: not only "I see fish", but "I can approach,
  smell, eat, climb near, hide under, scratch, sit on".
- Plan reports become meaningful because rejected actions can say
  `unreachable`, `blocked`, `cooldown`, `missing_ability`, or `unsafe`.
- The cat can remain locally autonomous while still moving toward the LLM's
  higher-level goal.

### Main Risk

Affordances can become a second action system if they are allowed to execute.
They should not. An affordance should describe possibility and cost. The only
executor should remain:

```text
IntentMessage -> CreatureWorker -> MotorCommand -> MalbersAnimalAdapter
```

### Good Affordance Shape

Each affordance should be small and serializable:

```json
{
  "id": "fish_crate:eat",
  "target_id": "fish_crate",
  "action": "eat",
  "tags": ["food", "smell:fresh_fish"],
  "distance": 2.4,
  "path_status": "safe",
  "cost": 0.25,
  "utility_hint": 0.8,
  "preconditions": ["reachable", "edible"],
  "failure_reason": ""
}
```

The LLM does not need every possible action. It needs the top ranked options:
food, danger, social targets, comfort/rest spots, interesting smells/sounds,
and traversal affordances relevant to the current intent.

## Critique Of Option C: Make The LLM One Decision Node Every 2-3 Seconds

This is tempting, but I would avoid making it the core loop.

### Why It Is Risky

- 2-3 seconds is slow for body control and fast for LLM reasoning.
- Network jitter will create uneven behavior unless Unity already has a local
  fallback.
- The LLM may repeat, contradict, or overcorrect because it only sees snapshots,
  not continuous animation state.
- It increases cost and backend load.
- It makes the cat feel less like an animal and more like it is waiting for
  remote instructions.

### When It Is Useful

The LLM can run every 2-3 seconds as a directive refresh if the backend is fast
enough, but Unity should still make the local decision at action boundaries.
The LLM tick should update:

- current high-level intent
- target or target class
- behavior weights
- urgency
- constraints
- optional plan sketch

It should not be the only source that chooses the exact next animation/motor
action.

## Recommended Architecture

Use three layers.

### Layer 1: Body Executor

Owned by Unity.

- Executes one `IntentMessage` at a time.
- Resolves targets.
- Applies navigation and animation through `CreatureWorker`.
- Records completion or rejection.
- Never asks the LLM what to do mid-animation.

### Layer 2: Local Behavior Policy

Owned by Unity.

- Reads mood, health, perception, current zones, navigation, and affordances.
- Uses weighted behavior nodes to decide the next micro-action.
- Keeps the cat alive when no explicit LLM plan exists.
- Biases toward the LLM directive but may override for safety, hunger, fear, or
  impossible actions.

### Layer 3: Slow Mind Directive

Owned by the LLM/backend.

The LLM returns a directive packet, not just raw action strings:

```json
{
  "intent": "SEEK_FOOD",
  "focus_target": "fish_crate",
  "urgency": 0.7,
  "duration_seconds": 12,
  "weights": {
    "seekFood": 2.0,
    "investigate": 1.2,
    "explore": 0.4,
    "rest": 0.2,
    "safety": 1.0
  },
  "plan_hint": [
    { "action": "go_to", "target": "fish_crate" },
    { "action": "smell", "target": "fish_crate" },
    { "action": "eat", "target": "fish_crate" }
  ],
  "constraints": ["avoid_fire", "stay_in_current_area"]
}
```

Unity may use the `plan_hint` when it is valid, but the local affordance/FSM
layer should remain allowed to adapt.

## Decision Cadence

Recommended timing:

- Body update: every Unity frame or existing worker tick.
- Local behavior decision: whenever the body becomes free, or every short local
  decision window.
- Affordance scan: periodic and event-driven, usually faster than the LLM tick.
- LLM directive tick: around 5-10 seconds by default, with event-triggered
  refresh for important changes.

If you want a 2-3 second LLM loop, use it as a high-level refresh rate, not as
the direct action loop. The cat should continue acting while a request is in
flight.

## Implementation Plan

### Phase 1: Stabilize The Current Weighted Directive Path

- Define the backend response fields for `weights`, `focus_target`, `urgency`,
  and `duration_seconds`.
- Add parsing in `AgentNetworkManager` for behavior weights.
- Apply parsed weights through `CreatureBlackboard.SetMindWeights(...)`.
- Add clamps and smoothing before weights reach `CatBehaviorFSM`.
- Add TTL/decay so old LLM directives fade back to defaults.
- Add debug output showing chosen state, final score, focus target, and source.

Done when the LLM can say "be more social toward player" or "bias toward food"
without sending a low-level plan.

### Phase 2: Add A Minimal Affordance Model

- Create an `ActionAffordance` data type.
- Create authorable affordance providers on objects or semantic proxies.
- Include action, target id, tags, distance, path status, cost, and failure
  reason.
- Build an affordance scanner that ranks reachable/doable actions.
- Add an `affordances` snapshot channel with a strict cap.
- Keep affordances descriptive only; do not let them execute directly.

Done when the backend can see "what the cat can do now" instead of only visible
entities.

### Phase 3: Make The FSM Choose From Affordances

- Update `CatBehaviorFSM.ActionFor(...)` so state-to-action selection can prefer
  valid affordances.
- For `SeekFood`, prefer reachable `eat` or `go_to food` affordances.
- For `Investigate`, prefer reachable smell/sound/novel object affordances.
- For `Rest`, prefer safe comfort/rest affordances.
- For `Safety`, prefer flee/hide/avoid affordances.
- Fall back to existing micro-actions when no affordance is available.

Done when a high-level state like `SeekFood` reliably turns into grounded local
behavior instead of generic wandering.

### Phase 4: Support Hybrid LLM Plans

- Let the LLM return optional `plan_hint` steps chosen from current affordance
  ids or target ids.
- Validate each step locally before enqueueing.
- If a step becomes invalid, skip or replan locally and report the reason.
- Let urgent directives interrupt local neutral behavior.
- Keep low-urgency directives as weight/focus bias only.

Done when the LLM can suggest a short plan, but Unity can safely adapt when the
world changes.

### Phase 5: Reporting And Evaluation

- Extend reports with rejection reasons from affordance validation.
- Include the active directive id/TTL in debug logs.
- Test backend delay, no backend, unreachable targets, disappearing targets,
  blocked paths, and conflicting safety/food/social goals.
- Add a play-mode debug panel for current directive, weights, top affordances,
  selected state, selected action, and last rejection.

Done when you can watch the cat for several minutes and understand both the
visible behavior and the internal reason trail.

## Strong Recommendation

Do not choose between "LLM modifies graph weights" and "affordance FSM".

Use both:

```text
LLM directive -> weights + focus + optional plan hint
Unity affordances -> valid local action candidates
CatBehaviorFSM -> picks grounded micro-action
CreatureWorker -> executes through the existing motor path
Report -> tells LLM what happened
```

That gives you the thing you want: a cat that is always busy like a real cat,
but still gradually bends toward what the LLM wants.

## Open Design Questions

- Should LLM weights be absolute values, deltas from defaults, or named profiles
  like `curious`, `hungry`, `cautious`, `social`?
- Should the LLM target a specific object id, a tag class like `food`, or both?
- How long should a directive remain active before decaying?
- Which actions are allowed to interrupt current local behavior?
- Should failed affordances be hidden from the LLM next tick, or included with a
  failure reason so the LLM learns why they failed?
- How many affordances can fit in the snapshot before it becomes noisy?

My current answer: start with clamped weight deltas, one optional focus target,
one optional plan hint, and the top 8-12 affordances. Keep the system small
until the behavior is readable in play mode.
