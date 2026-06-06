"""AWS Lambda entrypoint for the `recommendation-report` domain (report #2).

Terraform points the function's handler at ``handler.handler`` (see
``infra/aws-lambda/lambdas.tf``). This is the thin boundary: resolve the
attachment output, delegate to ``recommendation.generate_recommendation``, and
shape the response.

ADR-031 chain: recommendation is the **second report product**. It does NOT
re-derive from raw sessions — it **reuses attachment-report's output**, so the
attachment scoring is the single source of truth. Each user ends up with two
stored reports::

    results/{user_id}/attachment.json       (report #1, page #1)
    results/{user_id}/recommendation.json   (report #2, page #2)

This Lambda is invoked **automatically by S3** when attachment.json is created
(see the notification in ``infra/aws-lambda/lambdas.tf``), and also accepts
direct/manual invokes. Three event shapes are handled::

    # 1. S3 ObjectCreated notification (the automatic trigger)
    { "Records": [ { "s3": { "object": { "key": "results/<user_id>/attachment.json" } } } ] }

    # 2. inline (direct invoke / orchestrator passes the value)
    { "attachment": { "user_id": "...", "attachment_analysis": { ... } } }

    # 3. by reference (read results/{user_id}/attachment.json from S3)
    { "user_id": "vanillaSky00" }

``model`` is an optional override. Response (JSON)::

    { "user_id": "...", "recommendation": { ... } }
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_plus

from _s3io import get_result, put_result
from recommendation import generate_recommendation


def _coerce_event(event: Any) -> dict[str, Any]:
    """Accept a dict event or a JSON string body (API Gateway / SQS style)."""
    if isinstance(event, str):
        return json.loads(event)
    if isinstance(event, dict) and isinstance(event.get("body"), str):
        return json.loads(event["body"])
    return event if isinstance(event, dict) else {}


def _user_id_from_s3_event(payload: dict[str, Any]) -> str | None:
    """Extract the user_id from an S3 ObjectCreated notification.

    The trigger fires on ``results/{user_id}/attachment.json``, so the user id is
    the path segment between the ``results/`` prefix and the file name.
    """
    records = payload.get("Records")
    if not isinstance(records, list):
        return None
    for record in records:
        key = (((record or {}).get("s3") or {}).get("object") or {}).get("key") or ""
        parts = unquote_plus(key).split("/")
        if len(parts) >= 3 and parts[0] == "results" and parts[-1] == "attachment.json":
            return parts[1]
    return None


def _resolve_attachment(payload: dict[str, Any]) -> dict[str, Any]:
    """Get the attachment output: inline in the event, else from S3 by user_id."""
    inline = payload.get("attachment")
    if isinstance(inline, dict) and inline.get("attachment_analysis"):
        return inline

    user_id = payload.get("user_id")
    if user_id:
        stored = get_result(user_id, "attachment")
        if stored:
            return stored

    raise ValueError(
        "event must include 'attachment' (the attachment-report output) inline, "
        "or 'user_id' resolvable to results/{user_id}/attachment.json in S3"
    )


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    payload = _coerce_event(event)

    # S3 trigger: derive the user from the attachment.json key, then read it back.
    if not payload.get("attachment"):
        s3_user_id = _user_id_from_s3_event(payload)
        if s3_user_id:
            payload = {"user_id": s3_user_id, "model": payload.get("model")}

    attachment = _resolve_attachment(payload)
    user_id = attachment.get("user_id") or payload.get("user_id")
    if not user_id:
        raise ValueError("could not determine 'user_id' for the recommendation report")

    recommendation = generate_recommendation(
        user_id,
        attachment["attachment_analysis"],
        model=payload.get("model"),
    )
    result = {"user_id": user_id, "recommendation": recommendation}

    # Publish report #2 for the page. No-ops without MEWI_REPORT_RESULTS_BUCKET.
    put_result(user_id, "recommendation", result)
    return result
