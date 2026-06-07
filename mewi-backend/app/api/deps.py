from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection
from supabase import Client

from app.core.auth import ReportPrincipal, decode_report_read_token
from app.core.config import Settings, get_settings


SettingsDep: TypeAlias = Annotated[Settings, Depends(get_settings)]


def verify_api_key(
    connection: HTTPConnection,
    settings: SettingsDep,
) -> None:
    api_key = connection.headers.get("X-API-Key") or connection.query_params.get("api_key")
    if not api_key or api_key != settings.API_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


_report_bearer = HTTPBearer(auto_error=False)


def get_report_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_report_bearer)],
    settings: SettingsDep,
) -> ReportPrincipal:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing report read token.",
        )
    return decode_report_read_token(
        credentials.credentials,
        settings.MEWI_REPORT_READ_JWT_SECRET,
    )


ReportPrincipalDep: TypeAlias = Annotated[ReportPrincipal, Depends(get_report_principal)]


# Supabase
def get_supabase(connection: HTTPConnection) -> Client:
    return connection.app.state.supabase


SupabaseDep: TypeAlias = Annotated[Client, Depends(get_supabase)]


# Redis
def get_redis(connection: HTTPConnection) -> aioredis.Redis:
    return connection.app.state.redis


RedisDep: TypeAlias = Annotated[aioredis.Redis, Depends(get_redis)]


# Behavior graph (compiled once at startup, reused per tick)
def get_behavior_graph(connection: HTTPConnection):
    return connection.app.state.behavior_graph


BehaviorGraphDep: TypeAlias = Annotated[object, Depends(get_behavior_graph)]


# AgentTickService (thin Redis queue facade)
def get_agent_tick_service(
    connection: HTTPConnection,
    redis: RedisDep,
    settings: SettingsDep,
):
    from app.services.agent_tick.tick_service import AgentTickService

    if not hasattr(connection.app.state, "agent_tick_service"):
        connection.app.state.agent_tick_service = AgentTickService(
            redis=redis,
            settings=settings,
        )
    return connection.app.state.agent_tick_service


AgentTickServiceDep: TypeAlias = Annotated[object, Depends(get_agent_tick_service)]


# Report ingestion (ADR-014)
def _mewi_report_root() -> Path:
    """Resolve the mewi-report project root (sibling of mewi-backend)."""
    configured = os.getenv("MEWI_REPORT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # app/api/deps.py -> app -> mewi-backend -> repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "mewi-report"


def get_report_ingestion_service():
    """Build the local-file-backed report ingestion service.

    Storage, processed output, and context locations all default under
    ``mewi-report/pipeline`` (and ``mewi-report/src/data`` for the site copy),
    each overridable via env so a future S3/Lambda wiring swaps only here.
    """
    from app.services.report.service import ReportIngestionService
    from app.services.report.store import (
        LocalFileRawSessionStore,
        S3RawSessionStore,
    )
    from app.services.report.trigger import (
        LocalFileProcessingQueue,
        NoopProcessingTrigger,
        QueuedProcessingTrigger,
        SqsQueue,
    )

    report_root = _mewi_report_root()
    pipeline = report_root / "pipeline"

    def _path(env_key: str, default: Path) -> Path:
        configured = os.getenv(env_key, "").strip()
        return Path(configured).expanduser().resolve() if configured else default

    raw_root = _path("MEWI_REPORT_RAW_SESSION_DIR", pipeline / "raw_data" / "sessions")
    queue_dir = _path("MEWI_REPORT_QUEUE_DIR", pipeline / "queued_jobs")

    try:
        ready_threshold = int(os.getenv("MEWI_REPORT_READY_THRESHOLD", "1"))
    except ValueError:
        ready_threshold = 1

    # FastAPI does not generate reports. It stores raw sessions and either
    # enqueues the Lambda producer or no-ops in offline ingestion-only mode.
    processing_mode = os.getenv("MEWI_REPORT_PROCESSING_MODE", "noop").strip().lower() or "noop"

    if processing_mode == "sqs":
        raw_bucket = os.getenv("MEWI_REPORT_RAW_BUCKET", "").strip()
        queue_url = os.getenv("MEWI_REPORT_SQS_QUEUE_URL", "").strip()
        if not raw_bucket:
            raise RuntimeError("MEWI_REPORT_RAW_BUCKET is required when MEWI_REPORT_PROCESSING_MODE=sqs")
        if not queue_url:
            raise RuntimeError("MEWI_REPORT_SQS_QUEUE_URL is required when MEWI_REPORT_PROCESSING_MODE=sqs")
        raw_store = S3RawSessionStore(raw_bucket)
        trigger = QueuedProcessingTrigger(SqsQueue(queue_url))
    else:
        raw_store = LocalFileRawSessionStore(raw_root)

    if processing_mode == "queue":
        trigger = QueuedProcessingTrigger(LocalFileProcessingQueue(queue_dir))
    elif processing_mode == "noop":
        trigger = NoopProcessingTrigger()
    elif processing_mode != "sqs":
        raise RuntimeError(
            "Unsupported MEWI_REPORT_PROCESSING_MODE="
            f"{processing_mode!r}; use 'noop', 'queue', or 'sqs'. "
            "Inline FastAPI report generation has been removed; the Lambda owns processing."
        )
    return ReportIngestionService(raw_store, trigger, ready_threshold=ready_threshold)


ReportIngestionServiceDep: TypeAlias = Annotated[object, Depends(get_report_ingestion_service)]


def get_report_read_service():
    """Build the private-S3 report result reader for frontend reads."""
    from app.services.report.service import ReportReadService
    from app.services.report.store import S3ReportResultStore

    results_bucket = os.getenv("MEWI_REPORT_RESULTS_BUCKET", "").strip()
    if not results_bucket:
        raise RuntimeError("MEWI_REPORT_RESULTS_BUCKET is required for report read routes")
    return ReportReadService(S3ReportResultStore(results_bucket))


ReportReadServiceDep: TypeAlias = Annotated[object, Depends(get_report_read_service)]
