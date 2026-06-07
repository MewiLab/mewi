"""AWS Lambda entrypoint for the `attachment-report` domain.

Terraform points the function's handler at ``handler.handler`` (see
``infra/aws-lambda/lambdas.tf``). This is the thin boundary: parse the event,
delegate to ``attachment_analysis.analyze_sessions``, and shape the response.

Event contract (JSON)::

    {
      "user_id": "vanillaSky00",
      "sessions": [ { ...raw session payload or inner session... }, ... ],
      "model": "claude-..."        # optional model override
    }

``sessions`` accepts either full ``{schema_version, user_id, source, session}``
payloads or bare ``session`` objects — the analyser unwraps both. The same
shape arrives whether invoked directly, via SQS, or via EventBridge (the
ADR-014 hand-off from the backend report pipeline).

Response (JSON)::

    {
      "user_id": "vanillaSky00",
      "attachment_analysis": { type, modifier, summary, evidence[], scores,
                               confidence, caveat }
    }
"""

from __future__ import annotations

import json
from typing import Any

from attachment_analysis import analyze_sessions


def _coerce_event(event: Any) -> dict[str, Any]:
    """Accept a dict event or a JSON string body (API Gateway / SQS style)."""
    if isinstance(event, str):
        return json.loads(event)
    if isinstance(event, dict) and isinstance(event.get("body"), str):
        return json.loads(event["body"])
    return event if isinstance(event, dict) else {}


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    payload = _coerce_event(event)

    user_id = payload.get("user_id")
    sessions = payload.get("sessions")
    if not user_id or not isinstance(sessions, list) or not sessions:
        raise ValueError("event must include 'user_id' and a non-empty 'sessions' list")

    analysis = analyze_sessions(user_id, sessions, model=payload.get("model"))
    return {"user_id": user_id, "attachment_analysis": analysis}
