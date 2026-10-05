"""Processing trigger port.

FastAPI owns only the "is this user ready, and should a job be enqueued?"
decision. Report generation itself lives in the attachment-report Lambda, so
this module intentionally has no inline processor path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Protocol


class ProcessingTrigger(Protocol):
    def maybe_run(self, user_id: str, session_count: int) -> bool: ...


@dataclass(frozen=True)
class ProcessingJob:
    job_id: str
    user_id: str
    session_count: int
    enqueued_at: str


class ProcessingQueue(Protocol):
    def enqueue(self, user_id: str, session_count: int) -> ProcessingJob: ...


class NoopProcessingTrigger:
    """Never processes. Kept for tests / environments that only want ingestion."""

    def maybe_run(self, user_id: str, session_count: int) -> bool:
        return False


class LocalFileProcessingQueue:
    """Append-only local job queue for ADR-030's thin enqueue mode.

    This is intentionally tiny: the production replacement can be SQS/EventBridge
    while tests and local runs still exercise the route -> store -> enqueue seam.
    """

    def __init__(self, queue_dir: Path) -> None:
        self._queue_dir = queue_dir

    def enqueue(self, user_id: str, session_count: int) -> ProcessingJob:
        job = _new_processing_job(user_id, session_count)
        self._queue_dir.mkdir(parents=True, exist_ok=True)
        with (self._queue_dir / "report_processing_jobs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_job_payload(job), ensure_ascii=False) + "\n")
        return job


class SqsQueue:
    """Production report-processing queue backed by AWS SQS (ADR-032)."""

    def __init__(self, queue_url: str, client: object | None = None) -> None:
        if not queue_url.strip():
            raise ValueError("SqsQueue requires a queue URL")
        self._queue_url = queue_url.strip()
        if client is None:
            import boto3

            client = boto3.client("sqs")
        self._client = client

    def enqueue(self, user_id: str, session_count: int) -> ProcessingJob:
        job = _new_processing_job(user_id, session_count)
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(_job_payload(job), ensure_ascii=False),
        )
        return job


class QueuedProcessingTrigger:
    """Enqueues report processing and returns immediately."""

    def __init__(self, queue: ProcessingQueue) -> None:
        self._queue = queue

    def maybe_run(self, user_id: str, session_count: int) -> bool:
        self._queue.enqueue(user_id, session_count)
        return True


def _safe_segment(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_.-" else "_" for c in (value or "").strip())
    return cleaned or "unknown"


def _new_processing_job(user_id: str, session_count: int) -> ProcessingJob:
    now = datetime.now(UTC)
    safe_user = _safe_segment(user_id)
    return ProcessingJob(
        job_id=f"{safe_user}-{now:%Y%m%d%H%M%S%f}",
        user_id=user_id,
        session_count=session_count,
        enqueued_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _job_payload(job: ProcessingJob) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "user_id": job.user_id,
        "session_count": job.session_count,
        "enqueued_at": job.enqueued_at,
    }
