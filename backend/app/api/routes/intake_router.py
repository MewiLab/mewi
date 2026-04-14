"""
Intake endpoint — receives Unity (UnityWebRequest) payloads for testing.

Contract:
  POST /api/v1/intake
  Content-Type: application/json
  Body: { "test_string": "hello", "payload_data": { ... } }

Response: 200 {"status": "success", "received_data": { ... }}

The handler does NO business logic. It parses the body into IntakeTestPayload,
logs the parsed contents, and echoes the data back so results are immediately
visible in cURL / Postman and on the Render console.
"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intake"])

# Headers that add noise without useful debugging information
_SKIP_HEADERS = {
    "accept-encoding",
    "connection",
    "user-agent",
}


class IntakeTestPayload(BaseModel):
    """Flexible test payload for manual ingestion testing."""

    test_string: str | None = None
    payload_data: dict | None = None


def _fmt_json(value: object) -> str:
    """Pretty-print any JSON-serialisable value; fall back to repr."""
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


@router.post("/intake")
async def intake(request: Request, payload: IntakeTestPayload) -> JSONResponse:
    """
    Receive a test payload, log it verbosely, and echo it back.

    Example cURL:
        curl -X POST https://<host>/api/v1/intake \\
             -H "Content-Type: application/json" \\
             -d '{"test_string": "hello", "payload_data": {"key": "value"}}'
    """
    # ── Collect headers (skip low-value noise) ────────────────────────────────
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _SKIP_HEADERS
    }

    # ── Query params ──────────────────────────────────────────────────────────
    params = dict(request.query_params)

    parsed = payload.model_dump()

    # ── Emit one readable log block ───────────────────────────────────────────
    logger.info(
        "\n"
        "╔══════════════════ INTAKE REQUEST ══════════════════╗\n"
        "║  Method : %s\n"
        "║  Path   : %s\n"
        "╠══════════════════════════════════════════════════════\n"
        "║  HEADERS\n%s\n"
        "╠══════════════════════════════════════════════════════\n"
        "║  QUERY PARAMS\n%s\n"
        "╠══════════════════════════════════════════════════════\n"
        "║  PARSED PAYLOAD\n%s\n"
        "╚══════════════════════════════════════════════════════╝",
        request.method,
        request.url.path,
        _fmt_json(headers),
        _fmt_json(params) if params else "  (none)",
        _fmt_json(parsed),
    )

    return JSONResponse(content={"status": "success", "received_data": parsed})
