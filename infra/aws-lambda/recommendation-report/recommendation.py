"""Recommendation core for the `recommendation-report` Lambda — scaffold.

ADR-031 report #2: turn the **attachment report's output** into player-facing
recommendations. Input is the ``attachment_analysis`` block produced by
``attachment-report`` (type / scores / summary / evidence) — NOT raw sessions.
This keeps the attachment scoring as the single source of truth and lets the two
reports stay decoupled through the stored ``results/{user_id}/*.json`` files.

Wire the Claude Agent SDK run here (load the bundled SKILL, build a prompt from
the attachment analysis, call the agent, extract the result) following
``attachment-report/attachment_analysis.py:analyze_sessions`` as the template.
Keep this Lambda-friendly: input from the event, no mewi-report filesystem, no
file tools in the sandbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# SKILL.md ships next to this module inside the Lambda zip.
SKILL_PATH = Path(__file__).resolve().parent / "skills" / "recommendation" / "SKILL.md"


def generate_recommendation(
    user_id: str,
    attachment_analysis: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Produce the recommendation block for one user from the attachment report.

    ``attachment_analysis`` is the inner block from attachment-report's output.
    Not implemented yet — model it on
    ``attachment-report/attachment_analysis.py:analyze_sessions``.
    """
    raise NotImplementedError(
        "recommendation-report is scaffolded but not implemented. "
        "Model it on attachment-report/attachment_analysis.py:analyze_sessions, "
        "reading from the attachment_analysis block (report #1's output)."
    )
