---
name: recommendation
description: Scaffold. Produce a grounded, non-clinical recommendation block for a Mewi player from their attachment report (report #1's output). Fill this in following attachment-analysis/SKILL.md as the template.
---

# Recommendation (agent-driven) — scaffold

Placeholder skill for the `recommendation-report` Lambda (report #2). Define the
method here the same way `attachment-report/skills/attachment-analysis/SKILL.md`
does:

- **When to use** — after attachment-report has produced report #1; this run
  turns that result into recommendations.
- **Inputs** — the `attachment_analysis` block from report #1 (type, scores,
  summary, evidence). NOT raw sessions — reuse the attachment scoring.
- **Steps** — read the attachment signals and turn them into recommendations.
- **Output contract** — the exact JSON shape `recommendation.py` should return.
- **Tone & guardrails** — grounded, "your trace reads as", never "you are".

Until this is written, `recommendation.py:generate_recommendation` raises
`NotImplementedError`.
