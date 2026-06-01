"""Recommendation core for the `recommendation-report` Lambda — scaffold.

Empty counterpart to ``attachment-report/attachment_analysis.py``. Wire the
Claude Agent SDK run here (load the bundled SKILL, build a prompt from the
session digest, call the agent, extract the result) following the attachment
module as the template. Keep this Lambda-friendly: input from the event, no
mewi-report filesystem, no file tools in the sandbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# SKILL.md ships next to this module inside the Lambda zip.
SKILL_PATH = Path(__file__).resolve().parent / "skills" / "recommendation" / "SKILL.md"


def generate_recommendation(
    user_id: str,
    sessions: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Produce the recommendation block for one user. Not implemented yet."""
    raise NotImplementedError(
        "recommendation-report is scaffolded but not implemented. "
        "Model it on attachment-report/attachment_analysis.py:analyze_sessions."
    )
