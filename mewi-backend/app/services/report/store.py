"""Storage ports for report ingestion.

FastAPI stores raw session payloads and enqueues processing jobs. Processed
report JSON is produced by the attachment-report Lambda, so this module does not
contain processed-report writers or report-context loaders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from app.models.report import ReportProduct

REPORT_PRODUCTS: set[str] = {"attachment", "recommendation"}


class ReportResultNotFound(Exception):
    """Raised when a finished report product is not present."""


class ReportResultInvalid(Exception):
    """Raised when a finished report object is not valid JSON/dict data."""


def safe_segment(value: str) -> str:
    """Filesystem-safe path segment for user / session ids."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", (value or "").strip())
    return cleaned or "unknown"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


# ── raw session store ─────────────────────────────────────────────────────────

class RawSessionStore(Protocol):
    def put(self, user_id: str, session_id: str, data: dict[str, Any]) -> str: ...
    def count(self, user_id: str) -> int: ...
    def load_sessions(self, user_id: str) -> list[dict[str, Any]]: ...


class LocalFileRawSessionStore:
    """Atomic per-session writes under ``raw_data/sessions/{user}/{session}.json``.

    Replaces the inline ``_write_local_session`` / ``_count_user_sessions`` /
    ``_raw_session_root`` helpers that used to live in ``report_router.py``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, user_id: str, session_id: str, data: dict[str, Any]) -> str:
        user_segment = safe_segment(user_id)
        session_segment = safe_segment(session_id)
        storage_key = f"{user_segment}/{session_segment}.json"

        user_dir = self._root / user_segment
        user_dir.mkdir(parents=True, exist_ok=True)

        final_path = user_dir / f"{session_segment}.json"
        tmp_path = final_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(final_path)
        return storage_key

    def count(self, user_id: str) -> int:
        user_dir = self._root / safe_segment(user_id)
        if not user_dir.exists():
            return 0
        return sum(1 for path in user_dir.glob("*.json") if path.is_file())

    def load_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Return the inner ``session`` object from every stored raw payload."""
        user_dir = self._root / safe_segment(user_id)
        if not user_dir.exists():
            return []
        sessions: list[dict[str, Any]] = []
        for path in sorted(user_dir.glob("*.json")):
            raw = _read_json(path)
            if raw and isinstance(raw.get("session"), dict):
                sessions.append(raw["session"])
        return sessions


class S3RawSessionStore:
    """S3-backed raw-session store for ADR-032 production ingestion.

    Stores the same full ReportSessionPayload JSON that the local file store
    writes, but under ``raw/{user_id}/{session_id}.json`` in the configured
    bucket. The service can still call ``count`` immediately after ``put``; S3
    now provides strong read-after-write/list consistency for new objects.
    """

    def __init__(self, bucket: str, client: Any | None = None) -> None:
        if not bucket.strip():
            raise ValueError("S3RawSessionStore requires a bucket name")
        self._bucket = bucket.strip()
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._client = client

    def put(self, user_id: str, session_id: str, data: dict[str, Any]) -> str:
        key = _raw_session_key(user_id, session_id)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        return key

    def count(self, user_id: str) -> int:
        prefix = _raw_user_prefix(user_id)
        return sum(1 for key in self._iter_keys(prefix) if key.endswith(".json"))

    def load_sessions(self, user_id: str) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for key in self._iter_keys(_raw_user_prefix(user_id)):
            if not key.endswith(".json"):
                continue
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            raw = json.loads(resp["Body"].read().decode("utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("session"), dict):
                sessions.append(raw["session"])
        return sessions

    def _iter_keys(self, prefix: str):
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if isinstance(key, str):
                    yield key


def _raw_user_prefix(user_id: str) -> str:
    return f"raw/{safe_segment(user_id)}/"


def _raw_session_key(user_id: str, session_id: str) -> str:
    return f"{_raw_user_prefix(user_id)}{safe_segment(session_id)}.json"


# ── processed report result store ────────────────────────────────────────────

class ReportResultStore(Protocol):
    def get(self, user_id: str, product: ReportProduct) -> dict[str, Any]: ...
    def list(self, product: ReportProduct) -> list[dict[str, Any]]: ...


class S3ReportResultStore:
    """S3-backed reader for finished report products.

    The attachment/recommendation Lambdas own writes under
    ``results/{user_id}/{product}.json``. FastAPI only reads those private
    objects after application-level authorization succeeds.
    """

    def __init__(self, bucket: str, client: Any | None = None) -> None:
        if not bucket.strip():
            raise ValueError("S3ReportResultStore requires a bucket name")
        self._bucket = bucket.strip()
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._client = client

    def get(self, user_id: str, product: ReportProduct) -> dict[str, Any]:
        return self._get_key(_report_result_key(user_id, product))

    def list(self, product: ReportProduct) -> list[dict[str, Any]]:
        _validate_report_product(product)
        reports: list[dict[str, Any]] = []
        suffix = f"/{product}.json"
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix="results/"):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if isinstance(key, str) and key.endswith(suffix):
                    reports.append(self._get_key(key))
        return reports

    def _get_key(self, key: str) -> dict[str, Any]:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_s3_not_found(exc):
                raise ReportResultNotFound(key) from exc
            raise

        raw_body = resp["Body"].read()
        if isinstance(raw_body, bytes):
            raw_body = raw_body.decode("utf-8")
        try:
            data = json.loads(raw_body)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReportResultInvalid(key) from exc
        if not isinstance(data, dict):
            raise ReportResultInvalid(key)
        return data


def _report_result_key(user_id: str, product: ReportProduct) -> str:
    _validate_report_product(product)
    return f"results/{safe_segment(user_id)}/{product}.json"


def _validate_report_product(product: str) -> None:
    if product not in REPORT_PRODUCTS:
        raise ValueError(f"Unsupported report product: {product!r}")


def _is_s3_not_found(exc: Exception) -> bool:
    error = getattr(exc, "response", {}).get("Error", {})
    return error.get("Code") in {"NoSuchKey", "404", "NotFound"}
