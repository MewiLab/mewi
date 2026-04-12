"""
Intake endpoint — receives Unity (UnityWebRequest) payloads for testing.

Contract:
  POST /api/v1/intake
  Content-Type: application/json
  Body: any JSON object

Response: 200 {"status": "received"}

The handler does NO business logic. It formats and logs the full request
(headers, query-params, body) in a readable block so the cloud console
(Render, Fly.io, etc.) shows exactly what Unity sent.
"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intake"])

# Headers that add noise without useful debugging information
_SKIP_HEADERS = {
    "accept-encoding",
    "connection",
    "user-agent",
}


def _fmt_json(value: object) -> str:
    """Pretty-print any JSON-serialisable value; fall back to repr."""
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


@router.post("/intake")
async def intake(request: Request) -> JSONResponse:
    """
    Receive a Unity payload, log it verbosely, and return 200 OK.

    Unity side (C#):
        var req = new UnityWebRequest(url, "POST");
        req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(jsonBody));
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");
        await req.SendWebRequest();
    """
    # ── Collect headers (skip low-value noise) ────────────────────────────────
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _SKIP_HEADERS
    }

    # ── Query params ──────────────────────────────────────────────────────────
    params = dict(request.query_params)

    # ── Body — try JSON first, fall back to raw text ──────────────────────────
    raw_bytes = await request.body()
    try:
        body: object = await request.json()
    except Exception:
        body = raw_bytes.decode("utf-8", errors="replace") or "<empty body>"

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
        "║  BODY\n%s\n"
        "╚══════════════════════════════════════════════════════╝",
        request.method,
        request.url.path,
        _fmt_json(headers),
        _fmt_json(params) if params else "  (none)",
        _fmt_json(body),
    )

    return JSONResponse(content={"status": "received"})
