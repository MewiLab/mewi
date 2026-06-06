"""Tiny S3 result-store helper for the report Lambdas (ADR-031 chain).

Each Lambda directory is zipped self-contained, so this small helper is copied
per-Lambda rather than shared as a package. ``boto3`` ships in the AWS Lambda
Python runtime, so it is NOT in requirements.txt.

Layout (one prefix, two products):

    results/{user_id}/attachment.json       <- attachment-report writes
    results/{user_id}/recommendation.json   <- recommendation-report writes

All S3 use is gated on ``MEWI_REPORT_RESULTS_BUCKET``. When it is unset (local
runs / unit tests) the helpers no-op on write and return ``None`` on read, so the
Lambdas still work purely as ``event in -> JSON out``.
"""

from __future__ import annotations

import json
import os
from typing import Any


def results_bucket() -> str | None:
    return os.getenv("MEWI_REPORT_RESULTS_BUCKET", "").strip() or None


def _key(user_id: str, name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "_.-" else "_" for c in (user_id or "").strip()) or "unknown"
    return f"results/{safe}/{name}.json"


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
