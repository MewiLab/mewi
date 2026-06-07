# ADR-037: Agent Prompt And Memory Hygiene

## Status

Proposed

## Date

2026-06-07

## Scope

Backend agent prompts, `behavior_graph`, `context_builder`, `MemoryManager`,
`memory_consolidate`, `PlaceMemoryService`, domain intent proposal prompts,
and prompt-related tests.

This ADR complements ADR-034. ADR-034 defines the memory stores and live
micro-action pipeline. This ADR defines what the agent mind is allowed to see
from those stores.

## Context

Recent LangSmith traces show that the prompt visible to the agent contains too
much backend and Unity execution plumbing:

- repeated short-term memories say the same thing several times;
- `LAST TICK` and `SHORT TERM MEMORY` expose phrases such as
  `completed_with_rejections`, `adapter_refused`, `TimedOut`,
  `recovered_via_teleport:WarpedToNavMesh`, and "Unity reported previous
  execution status";
- selected future directives are written as memories even though Unity has not
  acted on them yet;
- social cues, nearby objects, and relationship context duplicate the same cats
  in multiple sections;
- place reflection can turn adapter-level failure telemetry into fake place
  memory;
- domain proposal prompts receive broad prompt context even when their domain
  only needs a narrow slice of it.

This makes the agent reason about integration state instead of the simulated
world. It also causes loops: if the need prompt repeatedly sees low energy plus
"sleep rejected", it keeps selecting `REST`, while the reflection layer may
convert the rejection into durable nonsense.

The Generative Agents paper gives a useful direction but should be adapted, not
copied blindly:

- memory streams hold observations, plans, and reflections as separate record
  types;
- reflections are higher-level thoughts generated periodically from salient
  evidence, not every raw event;
- reflections cite the records that support them;
- retrieval combines current context with relevant memories rather than dumping
  the whole stream into every prompt;
- plans are stored and retrieved as future commitments, not mistaken for past
  actions.

For Mewi, Unity should be treated as the embodied simulator. The agent should
usually assume that a selected directive was accepted and will be carried out by
Unity. Technical body/adapter failures are still important for engineers, but
they are not subjective cat experience unless they produce an in-world,
decision-relevant constraint.

## Decision

Adopt a prompt and memory hygiene contract:

1. Technical execution telemetry is private debug data.
2. Agent prompts see only in-world semantic experience.
3. Unity directives are assumed to complete or remain in progress unless there
   is a semantic world-level failure.
4. Short-term memory stores what happened, what is still intended, and what
   matters, not raw report fields.
5. Reflections are periodic evidence-backed abstractions, not forced summaries
   of every tick.
6. Domain prompts receive domain-specific context slices.
7. Prompt rendering deduplicates repeated facts before the LLM sees them.
8. Tests lint generated prompts for banned technical leakage and duplicate
   sections.

## Core Model

### Private Execution Telemetry

Raw `PlanExecutionReport` and normalized `MicroActionEvent` remain available for
audit, debugging, replay, metrics, and engineering recovery.

Private telemetry may contain:

```jsonc
{
  "report_status": "completed_with_rejections",
  "step_status": "rejected",
  "reason": "adapter_refused",
  "recovery": "recovered_via_teleport:WarpedToNavMesh",
  "timing": "TimedOut",
  "raw_step": {}
}
```

These fields must not appear in agent-facing prompts, place summaries, or
reflective memory text.

### Agent Experience Event

Before anything reaches the prompt or semantic memory layer, execution telemetry
is converted into an agent-facing event:

```jsonc
{
  "event_id": "cmd-12",
  "tick": 12,
  "actor_id": "gugu",
  "place_id": "House_2",
  "action": "vocalize",
  "target_id": "miso_cat",
  "outcome": "done",
  "visible_result": "Gugu made a small sound toward miso_cat.",
  "semantic_cause": "",
  "salience": 0.35,
  "memory_policy": "episodic"
}
```

Allowed outcomes:

- `done`: the action happened in-world;
- `in_progress`: the directive has been issued and Unity is expected to carry
  it forward;
- `no_visible_change`: no useful in-world change should be remembered;
- `blocked`: a visible world constraint changed future decisions;
- `interrupted`: a visible event or higher-priority need changed the plan.

`blocked` is only for semantic constraints such as target missing, path
unreachable, object unavailable, danger, or another actor occupying the target.
It is not for `adapter_refused`, unmapped action keys, telemetry timeout,
teleport recovery, or Unity internal report states.

### Plan Record

Selected intent is a plan, not a memory of completed action:

```jsonc
{
  "tick": 12,
  "intent": "REST",
  "target_id": "social_platform_1",
  "status": "intended",
  "style": "slow settle",
  "reasoning": "Energy is low and the platform is available."
}
```

Prompt wording should say "Current intention" or "The next directive is" rather
than "Selected next intent ... Unity will execute after this tick."

### Reflection Record

Reflections are generated from salient, deduplicated experience windows:

```jsonc
{
  "aspect": "social",
  "memory_kind": "reflection",
  "text": "Gugu often gives soft greetings around miso_cat and mewi_cat.",
  "evidence_ids": ["evt-8", "evt-9", "evt-11"],
  "tick_start": 8,
  "tick_end": 11,
  "salience": 0.55
}
```

Reflections must cite evidence ids internally, even if the final prompt renders
only the text. This keeps the paper's evidence-backed reflection pattern and
makes hallucinated summaries easier to detect.

## Prompt Contract

### Banned In Agent-Facing Prompts

The following tokens and concepts are debug-only:

- `Unity reported`;
- `PlanExecutionReport`;
- `adapter_refused`;
- `completed_with_rejections`;
- `completed_with_failures`;
- `rejected`;
- `failed` when it is only adapter/telemetry failure;
- `TimedOut`;
- `WarpedToNavMesh`;
- `recovered_via_teleport`;
- `backend`;
- `integration`;
- `raw_step`;
- "Unity will execute the directive after this tick".

The prompt may still express semantic constraints:

- "The food was out of reach."
- "The target cat is no longer nearby."
- "The path to the roof is not available."
- "The cat is already settling."

### Preferred Prompt Shape

Replace the broad repeated dynamic section with one typed `PromptFrame`:

```jsonc
{
  "self": {
    "place": "House_2",
    "current_activity": "settling",
    "body": ["energy is low", "fullness is high", "fear is low"]
  },
  "current_intention": {
    "intent": "REST",
    "target_id": "social_platform_1",
    "status": "intended"
  },
  "nearby_entities": [
    {
      "id": "miso_cat",
      "kind": "cat",
      "supports": ["SOCIALIZE", "INVESTIGATE"],
      "relationship": "trust is still forming"
    }
  ],
  "recent_experience": [
    "You made a small sound near miso_cat.",
    "You sat down."
  ],
  "relevant_reflections": [
    "Gugu often greets nearby cats with soft sounds."
  ],
  "place_memory": [
    "House 2 feels newly visited."
  ],
  "decision_focus": [
    "Energy is low, so use low-effort choices."
  ]
}
```

The rendered prompt can still be natural language, but it should be generated
from this deduplicated frame.

### Domain-Specific Views

The current domain prompts receive too much shared context. Each proposal domain
should receive only what it needs.

Need proposal sees:

- body state;
- fear/energy/fullness;
- semantic current activity;
- recent semantic body outcomes;
- only a compact note that social or exploration opportunity exists.

Exploration proposal sees:

- current place;
- reachable/new/stale places;
- curiosity/energy/fear;
- visible objects and sensory cues;
- related place reflections.

Social proposal sees:

- nearby cats/player;
- recent dialogue;
- relationship summaries;
- social affordances;
- fear/energy limits.

The arbiter sees:

- the domain proposals;
- available intent affordances;
- only the smallest shared frame needed to choose among proposals.

### Deduplication Rules

Before prompt rendering:

- merge duplicate entity mentions across `SOCIAL CUES`, `OBJECTS NEARBY`, and
  `OTHER CATS HERE`;
- merge repeated utterances such as `You said "mrrp?"` into a count or a single
  semantic line;
- keep only the newest semantic event per action-target pair unless repetition
  itself matters;
- collapse repeated low-energy/rest loops into one note;
- render related long-term reflection separately from recent experience;
- hide empty blocks instead of printing "(none)" unless absence is meaningful.

Example:

Before:

```text
action: Unity reported previous execution status completed_with_rejections.
Executed steps: vocalize(miso_cat)=completed because Completed;
look_at(mewi_cat)=completed because FaceTargetAligned;
vocalize(mewi_cat)=rejected because adapter_refused.
Selected next intent SOCIALIZE toward miso_cat; Unity will execute the directive after this tick.
social: You said "mrrp?"
social: You said "mrrp?"
```

After:

```text
Recent experience:
- You made a small sound toward miso_cat and looked toward mewi_cat.
- You have been giving soft greetings around nearby cats.
Current intention:
- SOCIALIZE near miso_cat.
```

## Memory Write Policy

### Raw Journal

Write all telemetry, including rejected steps and adapter reasons. This is the
lossless engineering stream.

### Hot Short-Term Memory

Write only semantic `AgentExperienceEvent` and `PlanRecord` rows. Technical
events with no visible world effect use `memory_policy=audit_only`.

### Place Memory

Place summaries may use:

- completed or observed in-world interactions;
- meaningful target/place constraints;
- repeated successful or blocked place use.

Place summaries must not use:

- report status alone;
- adapter refusal;
- telemetry timeout;
- teleport recovery;
- selected future intent.

### Reflective Memory

Reflection should run when a salience/importance threshold is reached, not just
because the tick count crossed a small number.

Recommended scoring:

- ordinary completed self action: `0.2-0.4`;
- interaction with another cat/player: `0.5-0.8`;
- new place or repeated place preference: `0.4-0.7`;
- semantic blocked constraint: `0.6-0.9`;
- technical-only adapter/telemetry event: `0.0` for reflection.

The reflection worker should:

1. gather recent semantic events and existing relevant reflections;
2. ask for 2-3 high-level questions worth answering;
3. retrieve evidence for each question;
4. generate compact insights with cited evidence ids;
5. store only insights that are useful for future decisions.

This follows the paper's reflection tree idea while preserving Mewi's tighter
game-simulation boundary.

## Implementation Plan

### Phase 1: Prompt Redaction

- Replace `format_previous_action_result(...)` with a semantic formatter that
  hides technical report states.
- Remove "Unity will execute the directive after this tick" from short-term
  memory text.
- Change `_previous_action_fact(...)` in `memory_consolidate` to write semantic
  experience, not report fields.
- Keep raw telemetry in `RawMemoryEvent.payload` and JSONL journal.
- Add prompt tests that assert banned tokens do not appear in generated domain
  prompts.

### Phase 2: PromptFrame And Dedup

- Build a canonical `PromptFrame` in `retrieve_memory` or `context_builder`.
- Deduplicate entities before sections are rendered.
- Split `nearby_entities` by kind and supported intents instead of rendering the
  same cats as social cues and objects.
- Merge repeated social utterances and repeated action notes.
- Add tests using the LangSmith-style prompt fixture from this ADR.

### Phase 3: Domain-Specific Renderers

- Give need, exploration, social, and arbiter prompts separate view builders.
- Keep persona static/cached; render only the relevant dynamic view per domain.
- Measure prompt length and duplicate-line count in tests.

### Phase 4: Evidence-Backed Reflection

- Add `evidence_ids` or equivalent evidence metadata to reflection summaries.
- Introduce salience thresholding so reflection is periodic and meaningful.
- Generate reflection questions before insights.
- Keep technical-only telemetry at salience `0.0` for reflection.

### Phase 5: Runtime Metrics

Track:

- prompt token count by domain;
- duplicate line count;
- banned token count;
- number of semantic events vs audit-only telemetry events;
- reflection source count and evidence coverage;
- repeated same-intent loops.

## Consequences

### Positive

- The cat stops reasoning about adapters, Unity report status, and backend
  integration.
- Prompts become shorter and more in-world.
- Reflection becomes more useful because it summarizes experiences, not
  plumbing.
- Debugging remains possible because raw telemetry is preserved separately.
- Domain proposal prompts become easier to inspect in LangSmith.
- Repeated technical failure loops should decrease because they no longer feed
  the agent mind as subjective failure memories.

### Negative

- Some real execution problems will be hidden from the agent unless they are
  translated into semantic constraints.
- The backend needs a stronger translation layer between telemetry and
  subjective memory.
- Tests must cover prompt leakage, not only parser shape.
- Engineers must inspect the journal or diagnostics for adapter problems rather
  than expecting the agent prompt to reveal them.

## Open Questions

- Should `blocked` semantic constraints come from Unity directly, or should the
  backend infer them from repeated telemetry plus unchanged world state?
- How long should a current intention stay visible if Unity has not yet reported
  an in-world completion?
- Should place memory store negative semantic constraints, or should those live
  only in action/reflection memory?
- What exact salience threshold should trigger reflection for a 6-second Unity
  tick loop?
- Should repeated intent loops be handled in the arbiter, the need proposer, or
  a separate plan-continuation node?

## Acceptance Criteria

- Generated agent prompts do not contain banned technical tokens.
- The LangSmith-style `completed_with_rejections` prompt becomes a short
  semantic prompt about current body state, nearby cats, and recent greetings.
- A pure `sleep rejected because adapter_refused` report produces no place
  memory and no subjective failure memory.
- Domain prompts no longer duplicate the same nearby cat in social, object, and
  world sections.
- Short-term memory distinguishes completed experience from current intention.
- Reflection summaries include evidence metadata and do not summarize
  technical-only events.
