"""Unit tests for report ingestion and the Lambda report producer.

FastAPI stores raw sessions and queues work; attachment-report Lambda owns the
processed report shape.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from app.models.report import ReportSessionPayload
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


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": FakeBody(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return self

    def paginate(self, **kwargs):
        bucket = kwargs["Bucket"]
        prefix = kwargs["Prefix"]
        keys = [
            key
            for (object_bucket, key) in self.objects
            if object_bucket == bucket and key.startswith(prefix)
        ]
        yield {"Contents": [{"Key": key} for key in sorted(keys)]}


class FakeSqsClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": "msg-1"}


def _lambda_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "infra" / "aws-lambda" / "attachment-report"


def _load_lambda_module(module_name: str, file_name: str):
    lambda_dir = _lambda_dir()
    if str(lambda_dir) not in sys.path:
        sys.path.insert(0, str(lambda_dir))
    spec = importlib.util.spec_from_file_location(module_name, lambda_dir / file_name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_attachment_handler():
    lambda_dir = Path(__file__).resolve().parents[4] / "infra" / "aws-lambda" / "attachment-report"
    if str(lambda_dir) not in sys.path:
        sys.path.insert(0, str(lambda_dir))
    spec = importlib.util.spec_from_file_location(
        "attachment_report_handler_under_test",
        lambda_dir / "handler.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_report_processor():
    return _load_lambda_module("attachment_report_processor_under_test", "report_processor.py")


# ── processor ─────────────────────────────────────────────────────────────────

def test_process_report_emits_render_schema():
    processor = _load_report_processor()
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]
    report = processor.process_report("u1", sessions, users={"u1": {"display_name": "U One"}})

    assert report["user_id"] == "u1"
    assert report["user"]["display_name"] == "U One"
    for key in ("meta", "summary", "cats", "radar", "attention_pct",
                "attachment_profile", "attachment_analysis", "timeline"):
        assert key in report
    assert set(report["cats"]) == {"mewi", "miso", "yuzu", "haru"}
    assert report["cats"]["mewi"]["trust_arc"] == [34]


def test_raw_v2_payload_ingests_and_normalizes_correlated_rows():
    processor = _load_report_processor()
    payload = ReportSessionPayload.model_validate(
        {
            "schema_version": "mewi.report.raw.v2",
            "user_id": "u1",
            "session": {
                "session_id": "s-v2",
                "session_index": 1,
                "timestamp_start": "2026-06-05T12:00:00Z",
                "timestamp_end": "2026-06-05T12:01:00Z",
                "close_reason": "game_session_closed",
                "duration_seconds": 60,
                "events": [
                    {
                        "event_id": "evt-001",
                        "correlation_id": "pcat-42",
                        "t": 4.0,
                        "actor": "player_cat",
                        "actor_id": "player",
                        "action": "player_meow",
                        "target_id": "mewi",
                        "phase": "completed",
                        "params": {
                            "behavior_key": "player_meow",
                            "motor_action": "vocalize",
                            "confidence": 1.0,
                        },
                    },
                    {
                        "event_id": "evt-002",
                        "correlation_id": "pcat-42",
                        "t": 4.1,
                        "actor": "system",
                        "action": "social_stimulus_delivered",
                        "target_id": "mewi",
                        "phase": "delivered",
                        "params": {"source_event_id": "evt-001"},
                    },
                    {
                        "event_id": "evt-003",
                        "correlation_id": "pcat-42",
                        "t": 5.0,
                        "actor": "cat",
                        "actor_id": "mewi",
                        "action": "answer_meow",
                        "target_id": "player",
                        "phase": "completed",
                        "status": "completed",
                        "trust_before": 10,
                        "trust_after": 25,
                        "params": {
                            "behavior_key": "answer_meow",
                            "motor_action": "vocalize",
                            "social_act_kind": "answer_meow",
                            "source_event_id": "evt-001",
                        },
                    },
                ],
            },
        }
    )

    session = payload.model_dump(mode="json")["session"]
    normalized = processor.normalize_session(session)

    assert normalized["events"][0]["actor"] == "human"
    assert normalized["events"][0]["actor_type"] == "player_cat"
    assert normalized["events"][0]["action_family"] == "affiliative_bid"
    assert normalized["events"][0]["params"]["target_id"] == "mewi"
    assert normalized["events"][1]["actor"] == "system"
    assert normalized["events"][2]["cat_id"] == "mewi"

    report = processor.process_report("u1", [session])
    assert report["cats"]["mewi"]["trust_arc"] == [25]
    assert report["interaction_signature"]["action_counts"]["player_meow"] == 1
    assert report["interaction_signature"]["action_family_pct"]["affiliative_bid"] == 100
    assert report["gesture_response_chains"][0]["delivered"] is True
    assert report["gesture_response_chains"][0]["cat_reaction"] == "answer_meow"
    assert report["attachment_features"]


def test_v2_multi_session_reused_event_ids_do_not_collapse_chains():
    processor = _load_report_processor()

    def session(session_id: str, index: int, trust_before: int, trust_after: int) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "session_index": index,
            "timestamp_start": f"2026-06-0{index}T12:00:00Z",
            "timestamp_end": f"2026-06-0{index}T12:01:00Z",
            "close_reason": "game_session_closed",
            "duration_seconds": 60,
            "events": [
                {
                    "event_id": "evt-000001",
                    "correlation_id": "pcat-42",
                    "t": 4.0,
                    "actor": "player_cat",
                    "actor_id": "player",
                    "action": "player_meow",
                    "target_id": "mewi",
                    "phase": "completed",
                    "params": {
                        "behavior_key": "player_meow",
                        "motor_action": "vocalize",
                    },
                },
                {
                    "event_id": "evt-000002",
                    "correlation_id": "pcat-42",
                    "t": 4.1,
                    "actor": "system",
                    "action": "social_stimulus_delivered",
                    "target_id": "mewi",
                    "phase": "delivered",
                    "params": {"source_event_id": "evt-000001"},
                },
                {
                    "event_id": "evt-000003",
                    "correlation_id": "pcat-42",
                    "t": 5.0,
                    "actor": "cat",
                    "actor_id": "mewi",
                    "action": "answer_meow",
                    "target_id": "player",
                    "phase": "completed",
                    "trust_before": trust_before,
                    "trust_after": trust_after,
                    "params": {"source_event_id": "evt-000001"},
                },
            ],
        }

    report = processor.process_report(
        "u1",
        [
            session("s1", 1, 10, 15),
            session("s2", 2, 20, 16),
        ],
    )

    assert report["interaction_signature"]["action_counts"]["player_meow"] == 2
    assert report["gesture_response_chains"][0]["trust_delta"] == 5
    assert report["gesture_response_chains"][1]["trust_delta"] == -4
    assert [chain["delivered"] for chain in report["gesture_response_chains"]] == [True, True]


def test_legacy_v1_human_actions_keep_attachment_profile_fallback():
    processor = _load_report_processor()
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]

    report = processor.process_report("u1", sessions)

    assert report["interaction_signature"]["action_counts"] == {}
    assert report["attachment_features"] == []
    assert report["attachment_analysis"]["type"] != "Insufficient player-cat evidence"


def test_process_report_applies_overrides():
    processor = _load_report_processor()
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]
    report = processor.process_report("u1", sessions, report_overrides={"summary": {"patience_pct": 99}})
    assert report["summary"]["patience_pct"] == 99


def test_process_report_agent_mode_is_deterministic_inside_lambda_processor():
    processor = _load_report_processor()
    sessions = [_payload("u1", "s1", 1).model_dump(mode="json")["session"]]
    report = processor.process_report("u1", sessions, attachment_mode="agent")

    assert "scores" in report["attachment_analysis"]
    assert report["attachment_analysis"]["caveat"].startswith("This is a behavioral reading")


def test_process_report_handles_empty_sessions():
    processor = _load_report_processor()
    report = processor.process_report("u1", [])
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


def test_queued_trigger_writes_local_processing_job(tmp_path: Path):
    store = FakeRawStore()
    queue = LocalFileProcessingQueue(tmp_path / "queue")
    service = ReportIngestionService(store, QueuedProcessingTrigger(queue), ready_threshold=1)

    result = service.ingest(_payload("u1", "s1", 1))

    assert result.processing_queued is True
    lines = (tmp_path / "queue" / "report_processing_jobs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    job = json.loads(lines[0])
    assert job["user_id"] == "u1"
    assert job["session_count"] == 1
    assert job["job_id"].startswith("u1-")


def test_sqs_queue_sends_compact_processing_job():
    client = FakeSqsClient()
    queue = SqsQueue("https://sqs.example/report-processing", client=client)

    job = queue.enqueue("u1", 2)

    assert job.user_id == "u1"
    assert client.messages[0]["QueueUrl"] == "https://sqs.example/report-processing"
    body = json.loads(client.messages[0]["MessageBody"])
    assert body == {
        "job_id": job.job_id,
        "user_id": "u1",
        "session_count": 2,
        "enqueued_at": job.enqueued_at,
    }
    assert "sessions" not in body


def test_s3_raw_session_store_preserves_full_payload_and_loads_inner_sessions():
    client = FakeS3Client()
    store = S3RawSessionStore("mewi-report-raw-v0", client=client)
    payload = _payload("vanilla sky", "session/1", 1).model_dump(mode="json")

    key = store.put("vanilla sky", "session/1", payload)

    assert key == "raw/vanilla_sky/session_1.json"
    assert store.count("vanilla sky") == 1
    stored = json.loads(client.objects[("mewi-report-raw-v0", key)].decode("utf-8"))
    assert stored["schema_version"] == "mewi.report.raw.v1"
    assert stored["session"]["session_id"] == "session/1"
    assert store.load_sessions("vanilla sky") == [payload["session"]]


# ── Lambda producer (full attachment product) ────────────────────────────────

def test_attachment_lambda_direct_invoke_emits_full_report(monkeypatch):
    handler = _load_attachment_handler()
    handler._USER_INFO_CACHE = None
    writes: list[tuple[str, str, dict[str, Any]]] = []

    def fake_analyze_sessions(user_id: str, raw_sessions: list[dict[str, Any]], *, model: str | None = None):
        assert user_id == "u1"
        assert raw_sessions[0]["schema_version"] == "mewi.report.raw.v1"
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

    monkeypatch.setattr(
        handler,
        "get_config_json",
        lambda name: {"users": {"u1": {"display_name": "U One", "handle": "u-one"}}},
    )
    monkeypatch.setattr(handler, "analyze_sessions", fake_analyze_sessions)
    monkeypatch.setattr(handler, "put_result", lambda user_id, name, obj: writes.append((user_id, name, obj)))

    report = handler.handler({"user_id": "u1", "sessions": [_payload("u1", "s1", 1).model_dump(mode="json")]})

    assert report["user_id"] == "u1"
    assert report["user"]["display_name"] == "U One"
    assert report["generation_mode"] == "llm_only"
    assert report["attachment_analysis"]["type"] == "Claude-backed attachment"
    for key in ("meta", "summary", "cats", "radar", "attention_pct",
                "attachment_profile", "attachment_analysis", "timeline"):
        assert key in report
    assert writes == [("u1", "attachment", report)]


def test_attachment_lambda_marks_llm_kb_when_analysis_signals_kb_use(monkeypatch):
    handler = _load_attachment_handler()
    handler._USER_INFO_CACHE = None

    def fake_analyze_sessions(user_id: str, raw_sessions: list[dict[str, Any]], *, model: str | None = None):
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
            "kb_used": True,
        }

    monkeypatch.setattr(handler, "get_config_json", lambda name: None)
    monkeypatch.setattr(handler, "analyze_sessions", fake_analyze_sessions)
    monkeypatch.setattr(handler, "put_result", lambda user_id, name, obj: None)

    report = handler.handler({"user_id": "u1", "sessions": [_payload("u1", "s1", 1).model_dump(mode="json")]})

    assert report["generation_mode"] == "llm+kb"
    assert "kb_used" not in report["attachment_analysis"]


def test_attachment_lambda_falls_back_to_deterministic_report_when_agent_fails(monkeypatch):
    handler = _load_attachment_handler()
    handler._USER_INFO_CACHE = None
    writes: list[tuple[str, str, dict[str, Any]]] = []

    def fail_analyze_sessions(user_id: str, raw_sessions: list[dict[str, Any]], *, model: str | None = None):
        raise RuntimeError("agent unavailable")

    monkeypatch.setattr(handler, "get_config_json", lambda name: None)
    monkeypatch.setattr(handler, "analyze_sessions", fail_analyze_sessions)
    monkeypatch.setattr(handler, "put_result", lambda user_id, name, obj: writes.append((user_id, name, obj)))

    session = _payload("u1", "s1", 1).model_dump(mode="json")["session"]
    report = handler.handler({"user_id": "u1", "sessions": [session]})

    assert report["user"]["display_name"] == "u1"
    assert report["generation_mode"] == "deterministic"
    assert "scores" in report["attachment_analysis"]
    assert writes == [("u1", "attachment", report)]


# ── local-file ingestion (tmp path, no real mewi-report tree) ────────────────

def test_local_file_ingestion_stores_raw_without_processing(tmp_path: Path):
    raw_root = tmp_path / "raw"

    raw_store = LocalFileRawSessionStore(raw_root)
    service = ReportIngestionService(raw_store, NoopProcessingTrigger(), ready_threshold=1)

    result = service.ingest(_payload("vanillasky_01", "s1", 1))

    assert result.session_count == 1
    assert result.processing_queued is False
    # raw stored atomically
    assert (raw_root / "vanillasky_01" / "s1.json").exists()
    assert not list(raw_root.rglob("*.tmp"))
