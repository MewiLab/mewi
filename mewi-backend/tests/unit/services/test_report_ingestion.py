"""Unit tests for the report ingestion service and pipeline (ADR-014).

Covers the storage round-trip, the processing-readiness threshold, and that
ingesting wires the pure processor through to processed output — all with
in-memory / tmp-path fakes, no network and no real mewi-report tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.report import ReportSessionPayload
from app.services.report.processor import process_report
from app.services.report.service import ReportIngestionService
from app.services.report.store import (
    LocalFileProcessedReportStore,
    LocalFileRawSessionStore,
    LocalFileReportSources,
)
from app.services.report.trigger import InlineProcessingTrigger, NoopProcessingTrigger


def _payload(user_id: str, session_id: str, session_index: int) -> ReportSessionPayload:
    return ReportSessionPayload.model_validate(
        {
            "schema_version": "mewi.report.raw.v1",
            "user_id": user_id,
            "session": {
                "session_id": session_id,
                "session_index": session_index,
                "timestamp_start": "2026-05-27T17:15:00Z",
                "duration_seconds": 120,
                "events": [
                    {"t": 4.0, "actor": "human", "action": "sit"},
                    {
                        "t": 30.0,
                        "actor": "cat",
                        "cat_id": "mewi",
                        "action": "settle",
                        "trust_before": 10,
                        "trust_after": 34,
                    },
                ],
            },
        }
    )


# ── in-memory fakes ───────────────────────────────────────────────────────────

class FakeRawStore:
    def __init__(self) -> None:
        self.sessions: dict[str, list[dict[str, Any]]] = {}

    def put(self, user_id: str, session_id: str, data: dict[str, Any]) -> str:
        self.sessions.setdefault(user_id, []).append(data["session"])
        return f"{user_id}/{session_id}.json"

    def count(self, user_id: str) -> int:
        return len(self.sessions.get(user_id, []))

    def load_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return list(self.sessions.get(user_id, []))


class RecordingTrigger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def maybe_run(self, user_id: str, session_count: int) -> bool:
        self.calls.append((user_id, session_count))
        return True


# ── processor ─────────────────────────────────────────────────────────────────

def test_process_report_emits_render_schema():
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]
    report = process_report("u1", sessions, users={"u1": {"display_name": "U One"}})

    assert report["user_id"] == "u1"
    assert report["user"]["display_name"] == "U One"
    for key in ("meta", "summary", "cats", "radar", "attention_pct",
                "attachment_profile", "attachment_analysis", "timeline"):
        assert key in report
    assert set(report["cats"]) == {"mewi", "miso", "yuzu", "haru"}
    assert report["cats"]["mewi"]["trust_arc"] == [34]


def test_process_report_applies_overrides():
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]
    report = process_report("u1", sessions, report_overrides={"summary": {"patience_pct": 99}})
    assert report["summary"]["patience_pct"] == 99


def test_process_report_agent_mode_uses_attachment_client(monkeypatch):
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]
    calls: list[tuple[str, int]] = []

    def fake_analyze_sessions(user_id: str, raw_sessions: list[dict[str, Any]]):
        calls.append((user_id, len(raw_sessions)))
        return {
            "type": "Claude-backed attachment",
            "modifier": "agent path",
            "summary": "Agent result.",
            "evidence": [],
            "scores": {
                "secure": 1,
                "anxious": 2,
                "avoidant": 3,
                "fearful_avoidant": 4,
            },
            "confidence": "low",
            "caveat": "test",
        }

    from app.services.report import attachment_client

    monkeypatch.setattr(attachment_client, "analyze_sessions", fake_analyze_sessions)
    report = process_report("u1", sessions, attachment_mode="agent")

    assert calls == [("u1", 1)]
    assert report["attachment_analysis"]["type"] == "Claude-backed attachment"


def test_process_report_agent_mode_falls_back_when_client_fails(monkeypatch):
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]

    def fail_analyze_sessions(user_id: str, raw_sessions: list[dict[str, Any]]):
        raise RuntimeError("agent unavailable")

    from app.services.report import attachment_client

    monkeypatch.setattr(attachment_client, "analyze_sessions", fail_analyze_sessions)
    report = process_report("u1", sessions, attachment_mode="claude")

    assert "scores" in report["attachment_analysis"]
    assert report["attachment_analysis"]["caveat"].startswith("This is a behavioral reading")


def test_process_report_handles_empty_sessions():
    report = process_report("u1", [])
    assert report["meta"]["sessions"] == 0
    assert report["meta"]["last_seen"] == ""


# ── service orchestration ─────────────────────────────────────────────────────

def test_ingest_stores_counts_and_triggers():
    store = FakeRawStore()
    trigger = RecordingTrigger()
    service = ReportIngestionService(store, trigger, ready_threshold=1)

    result = service.ingest(_payload("u1", "s1", 1))

    assert result.storage_key == "u1/s1.json"
    assert result.session_count == 1
    assert result.processing_queued is True
    assert trigger.calls == [("u1", 1)]


def test_ingest_respects_ready_threshold():
    store = FakeRawStore()
    trigger = RecordingTrigger()
    service = ReportIngestionService(store, trigger, ready_threshold=3)

    first = service.ingest(_payload("u1", "s1", 1))
    second = service.ingest(_payload("u1", "s2", 2))
    assert first.processing_queued is False
    assert second.processing_queued is False
    assert trigger.calls == []  # below threshold, never triggered

    third = service.ingest(_payload("u1", "s3", 3))
    assert third.processing_queued is True
    assert third.session_count == 3
    assert trigger.calls == [("u1", 3)]


def test_noop_trigger_never_runs():
    store = FakeRawStore()
    service = ReportIngestionService(store, NoopProcessingTrigger(), ready_threshold=1)
    result = service.ingest(_payload("u1", "s1", 1))
    assert result.processing_queued is False


# ── local-file end-to-end (tmp path, no real mewi-report tree) ────────────────

def test_local_file_pipeline_writes_processed_report(tmp_path: Path):
    raw_root = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    site_dir = tmp_path / "site"

    raw_store = LocalFileRawSessionStore(raw_root)
    processed_store = LocalFileProcessedReportStore(processed_dir, site_dir)
    sources = LocalFileReportSources(tmp_path / "user_info.json", tmp_path / "overrides")
    trigger = InlineProcessingTrigger(raw_store, processed_store, sources, attachment_mode="default")
    service = ReportIngestionService(raw_store, trigger, ready_threshold=1)

    result = service.ingest(_payload("vanillasky_01", "s1", 1))

    assert result.session_count == 1
    assert result.processing_queued is True
    # raw stored atomically
    assert (raw_root / "vanillasky_01" / "s1.json").exists()
    # processed written to both pipeline output and the site copy
    assert (processed_dir / "report_vanillasky_01.json").exists()
    assert (site_dir / "report_vanillasky_01.json").exists()
    # no temp files left behind
    assert not list(raw_root.rglob("*.tmp"))
    assert not list(processed_dir.glob("*.tmp"))
