from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, status

from app.api.deps import verify_api_key
from app.models.report import ReportSessionAcceptedResponse, ReportSessionPayload

router = APIRouter(
    prefix="/report",
    tags=["report"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/session",
    response_model=ReportSessionAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_report_session(payload: ReportSessionPayload) -> ReportSessionAcceptedResponse:
    """Validate and store one immutable raw report session from Unity."""
    storage_key = _write_local_session(payload)
    session_count = _count_user_sessions(payload.user_id)
    return ReportSessionAcceptedResponse(
        user_id=payload.user_id,
        session_id=payload.session.session_id,
        stored=True,
        session_count=session_count,
        processing_queued=False,
        storage_key=storage_key,
    )


def _write_local_session(payload: ReportSessionPayload) -> str:
    user_segment = _safe_segment(payload.user_id)
    session_segment = _safe_segment(payload.session.session_id)
    storage_key = f"{user_segment}/{session_segment}.json"

    user_dir = _raw_session_root() / user_segment
    user_dir.mkdir(parents=True, exist_ok=True)

    final_path = user_dir / f"{session_segment}.json"
    tmp_path = final_path.with_suffix(".json.tmp")
    data = payload.model_dump(mode="json")

    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(final_path)
    return storage_key


def _count_user_sessions(user_id: str) -> int:
    user_dir = _raw_session_root() / _safe_segment(user_id)
    if not user_dir.exists():
        return 0
    return sum(1 for path in user_dir.glob("*.json") if path.is_file())


def _raw_session_root() -> Path:
    configured = os.getenv("MEWI_REPORT_RAW_SESSION_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "mewi-report" / "pipeline" / "raw_data" / "sessions"


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", (value or "").strip())
    return cleaned or "unknown"
