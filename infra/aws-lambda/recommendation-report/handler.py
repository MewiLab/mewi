"""AWS Lambda entrypoint for the `recommendation-report` domain.

Scaffold only — mirrors the `attachment-report` layout so a new report Lambda
drops into the same convention (``handler.handler`` + a domain python module + a
bundled ``skills/`` method). Fill in ``recommendation.py`` and the SKILL, then
add ``"recommendation-report"`` to ``local.lambdas`` in
``infra/aws-lambda/lambdas.tf`` to deploy it.

Event contract (proposed)::

    {
      "user_id": "vanillaSky00",
      "sessions": [ { ...raw session... }, ... ]
    }

Response (proposed)::

    { "user_id": ..., "recommendation": { ... } }
"""

from __future__ import annotations

import json
from typing import Any

from recommendation import generate_recommendation


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

    recommendation = generate_recommendation(user_id, sessions, model=payload.get("model"))
    return {"user_id": user_id, "recommendation": recommendation}
