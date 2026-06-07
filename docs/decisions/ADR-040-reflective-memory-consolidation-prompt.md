# ADR-040: Reflective Memory Consolidation Prompt

## Status

Proposed

## Date

2026-06-07

## Scope

The shared `_CONSOLIDATION_PROMPT` in
`mewi-backend/app/agent/memory/memory_consolidate.py` and its two callers
`consolidate_memory_llm` and `consolidate_aspect_llm`, plus the consolidation
tests in `mewi-backend/tests/unit/agent/test_memory_consolidate.py`.

## Builds on

- ADR-037 (Agent Prompt And Memory Hygiene) — refines its Phase 4
  "evidence-backed reflection" with the concrete prompt design.
- ADR-034 (Live Micro-Action Memory Pipeline) — consumes the salience field that
  ADR-034/ADR-037 attach to events.

## Context

ADR-037 set the *policy* that reflection should be periodic, evidence-backed,
and free of technical leakage. It did not specify how the consolidation prompt
should be written, so the current `_CONSOLIDATION_PROMPT` still produces
summaries that drift from the cat's actual next-decision state.

A representative trace. Short-term memory across ticks 3–8 shows the intention
shifting from `SEEK_FOOD` (t=3–5) to `REST` (t=6–8), one reach constraint at
t=8 ("tried to eat a fat silver mackerel but couldn't reach it"), a persistent
nearby `kosto_cat`, and a transient `yuzu_cat` at t=7. The recalled long-term
reflection already states a strong mackerel-food preference plus kosto
awareness. The produced memory was:

> I have a strong preference for food near the fat silver mackerel, but my
> attempts to reach it have faced obstacles, highlighting the need to consider
> smaller steps or alternative strategies while remaining aware of the nearby
> kosto cat, which may influence my next actions.

Four problems, each mapping to a known technique:

1. **Stale current state.** The output is entirely about food-seeking; it never
   reflects that the newest intention is `REST`. The prompt treats all ticks as
   a flat bag, so the model pattern-matches the repeated `SEEK_FOOD` lines
   instead of the latest directive. Both Generative Agents retrieval (recency ×
   importance × relevance) and production context-engineering keep the newest
   state privileged and only summarize older context.

2. **Faithfulness drift.** A single t=8 constraint is pluralized into "my
   attempts ... have faced obstacles." Extract-then-generate and
   evidence-citation reflection (Generative Agents, Hindsight) reduce this by
   forcing the model to select supporting source facts before writing, and by
   separating evidence from inference.

3. **Length / format violation.** The output is one ~40-word run-on, ignoring
   the soft "1-2 short sentences." Chain-of-Density work shows a hard budget
   plus an explicit no-filler rule is needed, not a soft hint.

4. **Filler.** "...which may influence my next actions" carries no decision
   content. Salience-framed reflection asks for one decision-relevant insight,
   not a list with hedging.

The current prompt body:

```text
You write one cat's reflective long-term memory.
... Rewrite them as ONE compact reflective memory (1-2 short sentences) ...
Do more than list facts: include a grounded interpretation ...
Use only the stated facts as evidence ...
Treat "selected next intent" as a future directive, not as an attempted action.
Return only the memory text ...
SHORT-TERM MEMORY:
{short_term}
RELATED LONG-TERM MEMORY:
{related_memory}
```

## Decision

Rewrite `_CONSOLIDATION_PROMPT` to enforce four contracts, and pass the cat's
current intention as a first-class, mandatory field:

1. **Recency privilege.** The newest action memory's intention is the cat's
   current directive. It is hoisted out of the flat memory list into its own
   `CURRENT INTENTION` field and must appear in the output.
2. **Extract-then-generate.** The model first selects the 2–4 facts most
   relevant to the next decision (internal step), then writes from those.
3. **Single-event faithfulness.** A fact appearing once is one event; the prompt
   forbids pluralizing or generalizing it.
4. **Hard compactness.** At most 2 sentences / ~35 words, with hedging clauses
   explicitly banned and the known filler phrase given as a negative example.

The output stays free natural-language memory text (no rendered citations), but
the internal evidence-selection step preserves ADR-037's evidence-backed
reflection intent and makes hallucinated summaries easier to spot in tests.

### Revised prompt

```text
You maintain one cat's reflective long-term memory.

You are given this cat's recent short-term memories (ordered oldest->newest)
and any long-term memories recalled this tick. Produce ONE compact reflective
memory for the cat's next decision.

Follow these steps internally, then output only the final memory:

1. EVIDENCE: From the memories, pick the 2-4 facts most relevant to the next
   decision. Use only stated facts. The cat's CURRENT directive is the intention
   in the newest action memory and MUST be reflected in the output.
2. INSIGHT: State one grounded, decision-relevant pattern, preference,
   constraint, or lesson supported by those facts. You may infer cautious
   meaning from REPEATED facts, but do not invent events, motives, emotions,
   hesitation, failure, or outcomes not explicitly stated. A fact that appears
   once is a single event - do not pluralize or generalize it.
3. WRITE: Compress into at most 2 sentences, 35 words total. No hedging or
   filler clauses (e.g. "which may influence my next actions"). Every clause
   must carry a fact or the insight.

Treat "selected next intent" as a future directive, not an attempted action.
If the new memories merely repeat a recalled long-term memory, add only what is
new.

Return only the memory text - no quotes, labels, citations, or extra lines.

CURRENT INTENTION (must appear in output):
{current_intention}

SHORT-TERM MEMORY (oldest->newest):
{short_term}

RELATED LONG-TERM MEMORY:
{related_memory}
```

### Worked example

On the trace above, the revised prompt should yield something like:

> Resting now after failing to reach the fat silver mackerel I prefer; smaller
> approach steps may help next time, with a kosto cat consistently nearby.

This keeps the current `REST` directive, states the single constraint once,
drops the filler, and still carries the food preference and persistent social
context.

## Core Model

### Current intention extraction

`consolidate_memory_llm` already receives ordered `AspectMemory` rows. The newest
`action`-aspect memory's intention is extracted and rendered into
`{current_intention}`. When no action memory carries an intention, the field
renders `- (unknown)` and step 1's "MUST appear" clause is relaxed by the
absence of a value (the model simply has nothing to echo).

`consolidate_aspect_llm` folds older entries for a single aspect and has no live
"current" tick; it passes `current_intention="- (not applicable for this
aspect recap)"` so the recency clause is a no-op for that path.

### Salience reuse

ADR-034/ADR-037 attach a `salience` score to events. Where available, the
EVIDENCE step should prefer higher-salience facts (the t=8 blocked constraint at
~0.6–0.9 over a mundane "scanned around" at ~0.2). This is the third leg of the
Generative Agents retrieval function (importance) that consolidation does not
yet use. If salience is not yet plumbed to this layer, recency + the
2–4-fact cap is the interim selector.

## Implementation Plan

1. Replace `_CONSOLIDATION_PROMPT` with the revised text above, adding the
   `{current_intention}` placeholder.
2. In `consolidate_memory_llm`, extract the newest action intention and format it
   into `current_intention`; default to `- (unknown)` when absent.
3. In `consolidate_aspect_llm`, pass the not-applicable sentinel for
   `current_intention` so the shared template still formats.
4. Update `test_memory_consolidate.py` to assert: the current intention token
   appears in the rendered prompt; a single-occurrence fact is not pluralized in
   a fixture-driven check; output length stays within budget.
5. (Optional, follows ADR-037 Phase 4) feed `salience` into the EVIDENCE
   selection ordering when the field reaches this layer.

## Consequences

### Positive

- Consolidated memory tracks the cat's actual current directive instead of a
  stale repeated intent, so downstream need/social/exploration prompts read a
  truthful "what I'm doing now."
- Faithfulness improves: single events stay single, reducing invented failure
  patterns that can drive REST/SEEK loops.
- Memories get shorter and denser, lowering prompt cost (consistent with
  ADR-015) and improving LangSmith readability.
- No new infrastructure; it is a prompt change plus one extracted field.

### Negative

- The prompt is longer and more procedural; very small/cheap models may follow
  the internal steps less reliably than a single capable model.
- Extracting "current intention" couples consolidation to the action-memory
  text format; an intention-parsing helper is needed and must stay in sync with
  how intentions are written upstream.
- The internal evidence step is not rendered, so faithfulness must be checked by
  tests/eval rather than read off the output.

## Open Questions

- Should the current intention be parsed from action-memory text, or passed
  structurally from the plan record introduced in ADR-037?
- Should consolidation emit internal evidence ids (per ADR-037) for eval even
  though the stored memory text omits them?
- Is a 35-word budget right for a 6-second tick loop, or should it scale with how
  many distinct salient facts the window contains?
- When the newest intention conflicts with a strong recalled long-term
  preference, which should the insight foreground?

## Acceptance Criteria

- The rendered consolidation prompt contains a populated `CURRENT INTENTION`
  field whenever the newest action memory carries an intention.
- On the ADR trace fixture, the consolidated memory references `REST` (the
  current directive) and does not pluralize the single t=8 reach constraint.
- Consolidated output stays within the 2-sentence / ~35-word budget in tests.
- `consolidate_aspect_llm` still renders and runs with the not-applicable
  intention sentinel.
- No banned ADR-037 technical tokens appear in consolidated memory text.
