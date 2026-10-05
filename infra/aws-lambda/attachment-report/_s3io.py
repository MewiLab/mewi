"""Tiny S3 helper for the attachment-report Lambda (ADR-031/032 chain).

Each Lambda directory is zipped self-contained, so this small helper is copied
per-Lambda rather than shared as a package. ``boto3`` ships in the AWS Lambda
Python runtime, so it is NOT in requirements.txt.

Result layout (one prefix, two products):

    results/{user_id}/attachment.json       <- attachment-report writes
    results/{user_id}/recommendation.json   <- recommendation-report writes

Config layout (small producer reference data):

    config/user_info.json                    <- optional display-name/profile map

Raw-session layout (ADR-032 first hop):

    raw/{user_id}/{session_id}.json          <- FastAPI writes, attachment reads

Result S3 use is gated on ``MEWI_REPORT_RESULTS_BUCKET``. Raw-session reads
require ``MEWI_REPORT_RAW_BUCKET`` because an SQS job cannot be processed without
the durable inputs.
"""

from __future__ import annotations

import json
import os
from typing import Any


def results_bucket() -> str | None:
    return os.getenv("MEWI_REPORT_RESULTS_BUCKET", "").strip() or None


def raw_bucket() -> str | None:
    return os.getenv("MEWI_REPORT_RAW_BUCKET", "").strip() or None


def _safe_segment(value: str) -> str:
    return "".join(c if c.isalnum() or c in "_.-" else "_" for c in (value or "").strip()) or "unknown"


def _key(user_id: str, name: str) -> str:
    return f"results/{_safe_segment(user_id)}/{name}.json"


def _raw_prefix(user_id: str) -> str:
    return f"raw/{_safe_segment(user_id)}/"


def put_result(user_id: str, name: str, obj: dict[str, Any]) -> str | None:
    """Write ``results/{user_id}/{name}.json``. No-op (returns None) without a bucket."""
    bucket = results_bucket()
    if not bucket:
        return None
    import boto3  # provided by the Lambda runtime

    key = _key(user_id, name)
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def get_result(user_id: str, name: str) -> dict[str, Any] | None:
    """Read ``results/{user_id}/{name}.json``. Returns None without a bucket or if absent."""
    bucket = results_bucket()
    if not bucket:
        return None
    import boto3  # provided by the Lambda runtime

    client = boto3.client("s3")
    try:
        resp = client.get_object(Bucket=bucket, Key=_key(user_id, name))
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(resp["Body"].read().decode("utf-8"))


def get_config_json(name: str) -> dict[str, Any] | None:
    """Read ``config/{name}.json`` from the results bucket, if present."""
    bucket = results_bucket()
    if not bucket:
        return None
    import boto3  # provided by the Lambda runtime

    safe_name = _safe_segment(name)
    key = f"config/{safe_name}.json"
    client = boto3.client("s3")
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(resp["Body"].read().decode("utf-8"))


def get_raw_sessions(user_id: str) -> list[dict[str, Any]]:
    """List and read all raw session payloads for a user from MEWI_REPORT_RAW_BUCKET."""
    bucket = raw_bucket()
    if not bucket:
        raise ValueError("MEWI_REPORT_RAW_BUCKET is required for SQS-triggered attachment reports")

    import boto3  # provided by the Lambda runtime

    client = boto3.client("s3")
    sessions: list[dict[str, Any]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=_raw_prefix(user_id)):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if not isinstance(key, str) or not key.endswith(".json"):
                continue
            resp = client.get_object(Bucket=bucket, Key=key)
            raw = json.loads(resp["Body"].read().decode("utf-8"))
            if isinstance(raw, dict):
                sessions.append(raw)
    return sessions
