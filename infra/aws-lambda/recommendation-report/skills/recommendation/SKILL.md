---
name: recommendation
description: Scaffold. Produce a grounded, non-clinical recommendation block for a Mewi player from their session traces. Fill this in following attachment-analysis/SKILL.md as the template.
---

# Recommendation (agent-driven) — scaffold

Placeholder skill for the `recommendation-report` Lambda. Define the method
here the same way `attachment-report/skills/attachment-analysis/SKILL.md` does:

- **When to use** — what input triggers a recommendation run.
- **Inputs** — what the digest contains (per-cat trust arcs, action mix, etc.).
- **Steps** — how to derive signals and turn them into recommendations.
- **Output contract** — the exact JSON shape `recommendation.py` should return.
- **Tone & guardrails** — grounded, "your trace reads as", never "you are".

Until this is written, `recommendation.py:generate_recommendation` raises
`NotImplementedError`.
