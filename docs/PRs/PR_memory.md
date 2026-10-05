# PR: Reflective Memory Consolidation + Meaningful Social Communication

Implements **ADR-040** (Reflective Memory Consolidation Prompt) and the
functional core of **ADR-039** (Meaningful Cat Social Communication).

Branch: `feat/fix-backend_request`

## Summary

Two related fixes to the cat's "slow mind" so memory and social speech carry
decision-relevant meaning instead of stale or decorative text:

1. The memory consolidation prompt now privileges the cat's *current* intention,
   grounds every claim in stated facts, and stays compact.
2. Cat social speech becomes a grounded communication act (reply / invite /
   share-cue / request / boundary …) instead of generic noises (`mew?`,
   `mrrp`), and the social router resolves affordance/room id aliases.

No new infrastructure, no new LLM calls. Prompt + small deterministic logic.

## Motivation

A consolidation trace showed the reflective memory drifting from the cat's real
state: while the latest intention had shifted to `REST`, the summary still talked
about food-seeking, pluralized a single reach failure into "attempts", and ran on
with filler ("…which may influence my next actions"). Separately, the social
prompt asked for a "short cat-like utterance", so cats socialized without saying
anything another cat could use, and directed lines were silently downgraded to
broadcasts because `kosto_cat` (affordance id) never matched room member `kosto`.

## Changes

### ADR-040 — `mewi-backend/app/agent/memory/memory_consolidate.py`
- Rewrote `_CONSOLIDATION_PROMPT` as an internal EVIDENCE → INSIGHT → WRITE
  procedure with: a privileged `CURRENT INTENTION` field (recency weighting),
  extract-then-generate faithfulness, an explicit "a fact that appears once is a
  single event — do not pluralize" rule, and a hard ≤2-sentence / 35-word budget
  with the known filler phrase given as a negative example.
- Added `_current_intention_line()` — hoists the newest `action` memory's
  intention (`evidence.intent`, falling back to the `Current intention:` clause,
  else `- (unknown)`).
- Both callers updated: `consolidate_memory_llm` passes the live intention;
  `consolidate_aspect_llm` passes a not-applicable sentinel so the shared
  template still formats.

### ADR-039 — `mewi-backend/app/agent/arbitration/social_proposal.py`
- Rewrote `SOCIAL_PROPOSAL_PROMPT`: removed "short cat-like utterance" /
  "visible chirp"; added the speech-as-communication rules and the seven
  dialogue-act kinds.
- Added `build_communication_frame()` — distills heard inbox lines, sayable
  place/route/food/sense/body cues, and relationship cues from existing state
  into a `# COMMUNICATION FRAME` block. An empty frame nudges toward silence.
- Added `_finalize_social_act()` — collapses unknown dialogue acts to `message`,
  blanks generic noises / bare greetings to body language, and drops cue-less
  greetings.

### ADR-039 — `mewi-backend/app/social/service.py`
- Added `_creature_base()` + `_resolve_member()` so affordance ids
  (`kosto_cat`, `cat_kosto`) resolve to room members (`kosto`); applied in
  `_author_utterance` and in the bid-outcome comparison.
- Added `_is_recent_repeat()` anti-loop guard so a cat never re-publishes one of
  its own last three transcript lines.

## Testing

- `mewi-backend/tests/unit/agent/test_memory_manager.py` — asserts the prompt
  contains `CURRENT INTENTION` and that the newest `REST` directive is hoisted
  over the repeated `SEEK_FOOD` lines.
- `mewi-backend/tests/unit/social/test_social_service.py` — alias routing,
  aliased bid resolution, and repeat suppression.
- `mewi-backend/tests/unit/agent/test_social_proposal.py` (new) — communication
  frame distillation and the social-act validation contract.

Full unit suite: **173 passed, 1 skipped** (`make test`).

## Follow-ups (not in this PR)

- ADR-039 Phase 3: richer social memory-kind storage and a generic-`say`
  regression checker against live prompts.
- ADR-040 optional: feed event `salience` into the EVIDENCE selection ordering
  once it reaches the consolidation layer.
- ADR statuses remain **Proposed**; flip to **Accepted** if the team agrees the
  built core is in force.
