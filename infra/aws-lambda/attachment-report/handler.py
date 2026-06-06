"""AWS Lambda entrypoint for the `attachment-report` domain.

Terraform points the function's handler at ``handler.handler`` (see
``infra/aws-lambda/lambdas.tf``). This Lambda is the producer for the full
website-ready attachment product: parse the event, load raw sessions when the
event is a compact SQS job, derive the deterministic page shape, optionally
replace the nested ``attachment_analysis`` with the Claude-backed block, and
write the finished product to S3.

Event contract (JSON)::

    {
      "user_id": "vanillaSky00",
      "sessions": [ { ...raw session payload or inner session... }, ... ],
      "model": "claude-...",       # optional model override
      "attachment_mode": "agent"   # optional; default is agent, default/off
                                   # keeps deterministic analysis
    }

``sessions`` accepts either full ``{schema_version, user_id, source, session}``
payloads or bare ``session`` objects — the analyser unwraps both. Direct/manual
invokes pass sessions inline. Production SQS events carry only a compact job
pointer; the handler reads raw sessions from S3 before building the report.

Response (JSON)::

    {
      "user_id": "vanillaSky00",
      "generation_mode": "llm_only",
      "user": { ... },
      "meta": { ... },
      "summary": { ... },
      "cats": { ... },
      "radar": { ... },
      "attention_pct": { ... },
      "attachment_profile": [ ... ],
      "attachment_analysis": { type, modifier, summary, evidence[], scores,
                               confidence, caveat },
      "timeline": [ ... ]
    }
"""

from __future__ import annotations

import json
import os
import traceback
from typing import Any

from _s3io import get_config_json, get_raw_sessions, put_result
from attachment_analysis import analyze_sessions
from report_processor import process_report


_USER_INFO_CACHE: dict[str, dict[str, Any]] | None = None


def _coerce_event(event: Any) -> dict[str, Any]:
    """Accept a dict event or a JSON string body (API Gateway / SQS style)."""
    if isinstance(event, str):
        return json.loads(event)
    if isinstance(event, dict) and isinstance(event.get("body"), str):
        return json.loads(event["body"])
    return event if isinstance(event, dict) else {}


def _is_sqs_event(event: dict[str, Any]) -> bool:
    records = event.get("Records")
    return isinstance(records, list) and any(
        isinstance(record, dict) and "body" in record for record in records
    )


def _as_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the inner raw session object if this is a full payload."""
    inner = payload.get("session")
    return inner if isinstance(inner, dict) else payload


def _report_sessions(payloads: list[Any]) -> list[dict[str, Any]]:
    return [_as_session(item) for item in payloads if isinstance(item, dict)]


def _coerce_user_info(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    users = raw.get("users")
    return users if isinstance(users, dict) else {}


def _load_user_info() -> dict[str, dict[str, Any]]:
    """Read S3 config/user_info.json once per warm Lambda container."""
    global _USER_INFO_CACHE
    if _USER_INFO_CACHE is None:
        _USER_INFO_CACHE = _coerce_user_info(get_config_json("user_info"))
    return _USER_INFO_CACHE


def _wants_agent(payload: dict[str, Any]) -> bool:
    mode = str(
        payload.get("attachment_mode")
        or os.getenv("MEWI_REPORT_ATTACHMENT_MODE", "agent")
        or "agent"
    ).strip().lower()
    return mode not in {"default", "deterministic", "rule", "fallback", "none", "off"}


def _run_report(payload: dict[str, Any], *, allow_s3_sessions: bool) -> dict[str, Any]:
    user_id = payload.get("user_id")
    raw_sessions = payload.get("sessions")
    if not user_id:
        raise ValueError("event must include 'user_id'")
    user_id = str(user_id)
    if not isinstance(raw_sessions, list) or not raw_sessions:
        if not allow_s3_sessions:
            raise ValueError("event must include a non-empty 'sessions' list")
        raw_sessions = get_raw_sessions(user_id)
    if not raw_sessions:
        raise ValueError(f"no raw sessions found for user_id '{user_id}'")

    sessions = _report_sessions(raw_sessions)
    if not sessions:
        raise ValueError(f"no valid raw sessions found for user_id '{user_id}'")

    # ADR-033: production has no demo overrides. The Lambda builds the full
    # ProcessedAttachmentReport from raw sessions, with optional S3 user_info.
    result = process_report(
        user_id,
        sessions,
        users=_load_user_info(),
        report_overrides={},
        attachment_mode="default",
    )
    result["generation_mode"] = "deterministic"

    if _wants_agent(payload):
        try:
            analysis = analyze_sessions(user_id, raw_sessions, model=payload.get("model"))
        except Exception:
            # Keep the product available. SQS retries should be for bad inputs /
            # storage failures, not for optional narrative enrichment.
            print(f"attachment-report agent analysis failed for {user_id}; using deterministic report")
            traceback.print_exc()
        else:
            kb_used = bool(analysis.pop("kb_used", False) or analysis.pop("_kb_used", False))
            result["attachment_analysis"] = analysis
            # RAGFlow is not wired yet, so this is normally llm_only today.
            # When analyze_sessions signals KB use, the frontend can distinguish
            # the grounded path without another contract change.
            result["generation_mode"] = "llm+kb" if kb_used else "llm_only"

    # ADR-031 chain: publish report #1 so the page (and recommendation-report)
    # can read it. No-ops without MEWI_REPORT_RESULTS_BUCKET, so local/test runs
    # still just return the value.
    put_result(user_id, "attachment", result)
    return result


def _handle_sqs_event(event: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for index, record in enumerate(event.get("Records") or []):
        if not isinstance(record, dict):
            failures.append({"itemIdentifier": str(index)})
            continue
        item_id = str(record.get("messageId") or index)
        try:
            payload = _coerce_event(record.get("body"))
            _run_report(payload, allow_s3_sessions=True)
        except Exception:
            print(f"attachment-report failed SQS record {item_id}")
            traceback.print_exc()
            failures.append({"itemIdentifier": item_id})
    return {"batchItemFailures": failures}


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    payload = _coerce_event(event)
    if _is_sqs_event(payload):
        return _handle_sqs_event(payload)
    return _run_report(payload, allow_s3_sessions=False)
