# Mewi — 10-Minute Talk Outline (Academic Demo)

**Audience:** faculty panel (multiple professors), mixed CS / HCI / possibly
psychology interests.
**Goal:** show a working, research-grounded LLM agent system *and* an
interdisciplinary application (player attachment), with honest engineering
trade-offs.
**Length:** 10 minutes, 10 slides, ~1 min each. Leave 30s buffer + ~2 min Q&A
after.

Sourced from the ADRs in `docs/decisions/`. Where a newer ADR refines an older
one, the newer is authoritative (038/039 refine 010/011; 037/040 refine 034;
035 refines 030).

---

## Timing map

| # | Slide | Time | Cumulative |
|---|---|---|---|
| 1 | Title + one-sentence pitch | 0:30 | 0:30 |
| 2 | Problem & research framing | 1:00 | 1:30 |
| 3 | System overview — 3 apps | 1:00 | 2:30 |
| 4 | The tick: body ↔ mind | 1:00 | 3:30 |
| 5 | Agent cognition: propose → arbitrate → plan | 1:15 | 4:45 |
| 6 | Memory architecture (5 tiers) | 1:00 | 5:45 |
| 7 | Prompt hygiene & evidence-backed reflection | 1:00 | 6:45 |
| 8 | Cats that communicate (social) | 1:00 | 7:45 |
| 9 | The player attachment report | 1:15 | 9:00 |
| 10 | Status, limitations, future work | 0:45 | 9:45 |

---

## Slide 1 — Title (0:30)

**Visual:** Title "Mewi: LLM Cats That Live, Socialize, and Mirror How You
Bond." One screenshot of the fishing-village scene with cats. Names + course.

**Say:**
- "Mewi is a multi-agent LLM simulation of cats in a small open world. Each cat
  has its own mind, memory, and social life — and when you play *as* a cat, the
  system produces a report on your attachment style."
- One sentence on team + scope.

**Note:** Keep it to two sentences; the pitch is the hook, not the detail.

---

## Slide 2 — Problem & Research Framing (1:00)

**Visual:** Left = "believable agents" references; right = "attachment as
observable behavior." A small 2-column map.

**Say:**
- The hard problem: making agents *believable over time* — not one clever reply,
  but consistent memory, motivation, and social grounding.
- We build directly on **Generative Agents** (Park et al., 2023): observation →
  memory → reflection → planning. We adapt, not copy: ours is a real-time
  6-second game tick with a strict prompt budget.
- Dialogue grounded as **communication acts** (Strong & Mateas; dialogue-act
  control), not decorative chatter.
- The application twist: use the **Strange Situation / attachment theory** lens
  as *observable game telemetry* — not a clinical claim.

**Citations to show:** Park et al. 2304.03442; Strong & Mateas (AIIDE 2008);
attachment refs in ADR-035.

**Note:** This is the slide that earns credibility with professors — name the
prior work explicitly and state the adaptation honestly.

---

## Slide 3 — System Overview: 3 Apps (1:00)

**Visual:** Three boxes with the data contract arrows between them.
- `mewi-unity` (body + world) ⇄ `mewi-backend` (mind) over WebSocket
- `mewi-unity` → `mewi-report` (Astro site + Python/Lambda pipeline)

**Say:**
- **mewi-backend** — FastAPI + LangGraph, the cat's *mind*: perception, memory,
  social cognition. (ADR-003)
- **mewi-unity** — the cat's *body* and the game stage: Malbers locomotion,
  NavMesh, interaction state machines, player input.
- **mewi-report** — turns a finished session into a player attachment report.
- Key principle: **backend owns cognition and the world model; Unity owns the
  body and cadence.** (ADR-010)

**Note:** This is the mental model for the whole talk — point back to it later.

---

## Slide 4 — The Tick: Body ↔ Mind (1:00)

**Visual:** Sequence diagram (simplified ADR-011): Unity → WebSocket → worker →
LangGraph → plan back to Unity. Label "Unity is the cadence authority."

**Say:**
- One WebSocket per cat. Each tick Unity sends a *snapshot + previous report*;
  backend returns a *plan* (actions + dialogue). (ADR-004/011/023)
- Unity won't send the next tick until the last plan returns → clean per-cat
  ordering, no runaway loops.
- The graph is **8 nodes, compiled once, shared by every cat** — only **two
  nodes call the LLM** (choose intent, plan steps). Everything else is
  deterministic Python.
- Reliability: Unity's watchdog *repaths-then-warps* so every action terminates
  (ADR-005) — which is what lets the backend safely fire-and-forget.

**Note:** The "exactly two LLM calls per tick" line is your cost-discipline
headline — professors will ask about scalability/cost; pre-empt it.

---

## Slide 5 — Agent Cognition: Propose → Arbitrate → Plan (1:15)

**Visual:** ADR-018 diagram. Three parallel proposers (Need / Exploration /
Social) → LLM arbiter → planner. Before/after: "one mind invents" vs "propose
then choose."

**Say:**
- Naive design: hand the whole scene to one LLM and ask "what now?" → **drive
  lock-in** and **plan echo** (same `SEEK_FOOD`, same plan, every tick).
- Fix: split *enumeration* from *selection*. Deterministic proposers each always
  surface their angle — Need Assessment always raises the most-neglected drive,
  Social always raises a co-located peer.
- The LLM's job shrinks to **arbitrating a small labeled candidate set** — an
  easier, more steerable call. Planner adds novelty re-ask to break echo.
- Crucially: **still two LLM calls** — all new machinery is cheap Python.
  (ADR-016 toolkit, ADR-018 wiring)

**Note:** This is your strongest "architecture insight" slide. The takeaway:
structure the problem so the LLM does only what LLMs are good at.

---

## Slide 6 — Memory Architecture: 5 Tiers (1:00)

**Visual:** Table/stack: Hot STM · JSONL journal · Reflective summaries
(Supabase + embeddings) · Place memory · Social relationships. (ADR-034)

**Say:**
- Different truths need different stores. Recent facts stay *hot*; a lossless
  *journal* enables replay/debug; *reflective summaries* (LLM, ~1-min windows,
  embeddings, salience) carry long-term meaning; *place memory* makes
  exploration purposeful; *social* memory tracks who's nearby and the bond.
- Design rule: low-level micro-actions never become prompt clutter, and
  reflective summaries never pretend to be lossless facts.
- Honest scope: Neo4j causal graph is *deferred* until there's a real traversal
  consumer — we didn't add infra we couldn't justify.

**Note:** Mention the salience-weighted recall — that's the Generative Agents
retrieval idea (recency × importance × relevance) made concrete.

---

## Slide 7 — Prompt Hygiene & Evidence-Backed Reflection (1:00)

**Visual:** Before/after prompt snippet (ADR-037): raw `completed_with_rejections`
/ `adapter_refused` telemetry → clean semantic "you made a small sound near
miso_cat."

**Say:**
- We found a real failure mode: engine telemetry leaking into the cat's mind
  caused **failure loops** (it kept reasoning about adapter errors and
  re-selecting REST). (ADR-037)
- Contract: agent prompts see only *in-world semantic experience*; technical
  telemetry stays private for debugging.
- Reflection is **periodic + evidence-backed**: select supporting facts first,
  then write; privilege the newest intention; ban pluralizing single events.
  (ADR-040) — this directly mirrors the paper's evidence-citing reflection.

**Note:** Frame as "a lesson learned," not just a feature — panels reward
showing you debugged a non-obvious systemic problem.

---

## Slide 8 — Cats That Communicate (Social) (1:00)

**Visual:** Two cats, a shared room, inbox/transcript; a "communication frame"
chip → a meaningful line. (ADR-038/039)

**Say:**
- Backend owns shared rooms, inboxes, transcripts, relationships; Unity only
  renders. (ADR-010/011)
- **Subjective speakers:** each cat's *own* LLM authors only its own line; it can
  never write another cat's reply. Replies happen on the listener's next tick —
  bounded, no runaway LLM-to-LLM loop. (ADR-038)
- Speech is a **communication act** (invite, share-cue, reply, boundary…),
  grounded in a frame of what was heard / what need / what object matters — so we
  get "Fish smell is near the boxes," not "mew?" (ADR-039)

**Note:** Tie back to slide 2's dialogue-act citation. This is the
believability payoff.

---

## Slide 9 — The Player Attachment Report (1:15)

**Visual:** Pipeline: Unity raw v2 (player-cat actions) → FastAPI store/enqueue →
SQS → Lambda (deterministic features → narrative) → Astro report. Plus the
theory→observable mapping table. (ADR-029/030–035)

**Say:**
- When *you* play a cat, every action is logged: a **24-action vocabulary** (meow,
  groom, sit-near, smell, push, flinch…) plus correlated NPC-cat reactions and
  trust deltas. (ADR-029/035)
- Deterministic layer first: count actions → action families → causal
  gesture→response chains → 0–100 **attachment features** with evidence ids.
  *Then* an LLM narrates — but only over those facts (it can't invent counts).
- Theory mapping: proximity bids, respect-for-distance, repair-after-rupture,
  pursuit pressure → secure / anxious / avoidant / fearful *leanings*.
- **Stated as game telemetry, not diagnosis** — important ethical framing.

**Note:** This is the interdisciplinary slide; psychology-leaning professors will
focus here. Emphasize the non-clinical caveat and the auditability (evidence ids).

---

## Slide 10 — Status, Limitations, Future Work (0:45)

**Visual:** Small "Accepted vs Proposed" legend; 3 bullets of future work.

**Say:**
- Built & running: tick loop, two-LLM cognition, 5-tier memory, place memory,
  social rooms, the report pipeline end-to-end (deterministic + narrative).
- Proposed / in-progress: subjective social speakers, reflective consolidation
  prompt, navmesh corridor hardening.
- Future: Neo4j causal/trust graph; durable relationship storage; attachment
  feature tuning on real sessions; LLM social moderator behind the existing seam.
- One-line close: "A cost-disciplined, research-grounded agent stack — and a
  novel use of attachment theory as observable play."

**Note:** End on the close line, then "happy to take questions."

---

## If you must cut to ~6 slides
Keep 1, 3, 5, 6+7 (merged), 8, 9. Drop 2 (fold citations into 5/8), 4 (fold the
tick into slide 3), 10 (say it verbally).

## Likely professor questions — be ready
- **Cost/scale?** Two LLM calls/tick, prompt-cache discipline (ADR-015),
  fire-and-forget writes off the critical path (ADR-018).
- **Why not one big agent loop?** Believability needs separated memory/reflection
  + deterministic enumeration to avoid lock-in (ADR-016/018).
- **Is the attachment claim valid?** It's *Strange-Situation-inspired game
  telemetry*, non-clinical, evidence-id auditable (ADR-035).
- **Evaluation?** Honest answer: prompt-leakage lint tests, smoke baselines,
  drive-rotation acceptance checks; formal human eval is future work.
- **What's actually working vs designed?** Point to ADR Status lines (Accepted vs
  Proposed).
```
