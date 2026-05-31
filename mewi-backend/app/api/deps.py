from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, TypeAlias

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from starlette.requests import HTTPConnection
from supabase import Client

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
        LocalFileProcessedReportStore,
        LocalFileRawSessionStore,
        LocalFileReportSources,
    )
    from app.services.report.trigger import InlineProcessingTrigger

    report_root = _mewi_report_root()
    pipeline = report_root / "pipeline"

    def _path(env_key: str, default: Path) -> Path:
        configured = os.getenv(env_key, "").strip()
        return Path(configured).expanduser().resolve() if configured else default

    raw_root = _path("MEWI_REPORT_RAW_SESSION_DIR", pipeline / "raw_data" / "sessions")
    processed_dir = _path("MEWI_REPORT_PROCESSED_DIR", pipeline / "processed_data")
    site_data_dir = _path("MEWI_REPORT_SITE_DATA_DIR", report_root / "src" / "data")
    user_info_path = _path("MEWI_REPORT_USER_INFO", pipeline / "user_info.json")
    overrides_dir = _path("MEWI_REPORT_OVERRIDES_DIR", pipeline / "report_overrides")

    try:
        ready_threshold = int(os.getenv("MEWI_REPORT_READY_THRESHOLD", "1"))
    except ValueError:
        ready_threshold = 1

    # Runtime ingestion prefers the Claude skill, with deterministic fallback;
    # set MEWI_REPORT_ATTACHMENT_MODE=default to force the pure rule.
    attachment_mode = os.getenv("MEWI_REPORT_ATTACHMENT_MODE", "agent").strip() or "agent"

    raw_store = LocalFileRawSessionStore(raw_root)
    processed_store = LocalFileProcessedReportStore(processed_dir, site_data_dir)
    sources = LocalFileReportSources(user_info_path, overrides_dir)
    trigger = InlineProcessingTrigger(raw_store, processed_store, sources, attachment_mode)
    return ReportIngestionService(raw_store, trigger, ready_threshold=ready_threshold)


ReportIngestionServiceDep: TypeAlias = Annotated[object, Depends(get_report_ingestion_service)]
