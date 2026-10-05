#!/usr/bin/env python3
"""Local Unity-close -> processed report -> Astro render smoke runner.

This script is intentionally local/deterministic. It lets you validate the
Unity raw report contract and frontend rendering without AWS SQS/S3 or Claude.

Common flows:

  # After Unity posts to local FastAPI, process all stored sessions for the user.
  python3 pipeline/scripts/e2e_unity_report.py --user vanillasky_01

  # Post one Unity-saved JSON to local FastAPI, then process the stored sessions.
  API_SECRET_TOKEN=dev-secret-change-me \
    python3 pipeline/scripts/e2e_unity_report.py --post ~/session.json

  # Skip FastAPI and process one or more Unity JSON files directly.
  python3 pipeline/scripts/e2e_unity_report.py --raw-file ~/session.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPORT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = REPORT_ROOT.parent
LAMBDA_DIR = REPO_ROOT / "infra" / "aws-lambda" / "attachment-report"
RAW_ROOT = REPORT_ROOT / "pipeline" / "raw_data" / "sessions"
PROCESSED_DIR = REPORT_ROOT / "pipeline" / "processed_data"
STATIC_DATA_DIR = REPORT_ROOT / "src" / "data"
USER_INFO_PATH = REPORT_ROOT / "pipeline" / "user_info.json"


def main() -> int:
    args = parse_args()

    posted_user_ids = post_payloads(args)
    user_id = args.user or first_value(posted_user_ids)
    payloads = load_input_payloads(args, user_id)
    if not payloads:
        raise SystemExit("No raw report payloads found. Pass --raw-file, --post, or --user with stored sessions.")

    user_id = args.user or payload_user_id(payloads[0]) or user_id
    if not user_id:
        raise SystemExit("Could not infer user_id. Pass --user.")

    report = run_attachment_lambda(user_id, payloads, allow_s3_result=args.allow_s3_result)
    report_id = args.report_id or report.get("user", {}).get("report_slug") or report.get("user_id") or user_id
    write_report(report_id, report)

    routes = load_report_routes(STATIC_DATA_DIR)
    route = next((item for item in routes if item["dataFileId"] == report_id), None)
    route_id = route["routeId"] if route else safe_segment(report.get("user", {}).get("handle") or report_id)
    route_url = f"{args.frontend_url.rstrip('/')}/user/report/{route_id}/"

    print_summary(report_id, route_url, report)

    if args.build:
        run_build()

    if args.verify_url:
        verify_render(route_url)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Unity report E2E smoke.")
    parser.add_argument("--user", help="Stable report user_id, e.g. vanillasky_01.")
    parser.add_argument("--raw-file", action="append", default=[], help="Unity raw payload JSON to process directly. May be repeated.")
    parser.add_argument("--raw-dir", help="Directory of raw payload JSONs. Defaults to pipeline/raw_data/sessions/{user}.")
    parser.add_argument("--post", action="append", default=[], help="Unity raw payload JSON to POST to FastAPI before processing. May be repeated.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="FastAPI base URL for --post.")
    parser.add_argument("--api-key", default=os.getenv("API_SECRET_TOKEN", "dev-secret-change-me"), help="X-API-Key value for --post.")
    parser.add_argument("--report-id", help="Output id for report_<id>.json. Defaults to user.report_slug/user_id.")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:4321", help="Astro dev/preview base URL used in printed route.")
    parser.add_argument("--verify-url", action="store_true", help="Fetch the printed Astro route and assert key report text is present.")
    parser.add_argument("--build", action="store_true", help="Run npm run build after writing src/data.")
    parser.add_argument("--allow-s3-result", action="store_true", help="Allow Lambda helper to write MEWI_REPORT_RESULTS_BUCKET if set.")
    return parser.parse_args()


def first_value(values: list[str]) -> str | None:
    return values[0] if values else None


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return value


def payload_user_id(payload: dict[str, Any]) -> str:
    value = payload.get("user_id")
    return str(value).strip() if value else ""


def post_payloads(args: argparse.Namespace) -> list[str]:
    user_ids: list[str] = []
    for raw_path in args.post:
        path = Path(raw_path).expanduser().resolve()
        payload = read_json(path)
        user_id = payload_user_id(payload)
        if user_id:
            user_ids.append(user_id)
        post_payload(args.backend_url, args.api_key, payload)
        print(f"POST ok: {path.name} -> {args.backend_url.rstrip('/')}/api/v1/report/session")
    return user_ids


def post_payload(backend_url: str, api_key: str, payload: dict[str, Any]) -> None:
    url = f"{backend_url.rstrip('/')}/api/v1/report/session"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 300:
                raise RuntimeError(f"POST failed with HTTP {response.status}: {response.read().decode('utf-8')}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST failed with HTTP {exc.code}: {detail}") from exc


def load_input_payloads(args: argparse.Namespace, user_id: str | None) -> list[dict[str, Any]]:
    files = [Path(item).expanduser().resolve() for item in args.raw_file]

    if not files:
        raw_dir = Path(args.raw_dir).expanduser().resolve() if args.raw_dir else None
        if raw_dir is None and user_id:
            raw_dir = RAW_ROOT / user_id
        if raw_dir and raw_dir.exists():
            files = sorted(raw_dir.glob("*.json"))

    payloads = [read_json(path) for path in files]
    if args.post and not args.raw_file and not args.raw_dir and user_id:
        # Prefer the backend-stored shape after posting, when available.
        stored = sorted((RAW_ROOT / user_id).glob("*.json"))
        if stored:
            payloads = [read_json(path) for path in stored]
    return payloads


def load_user_info() -> dict[str, dict[str, Any]]:
    if not USER_INFO_PATH.exists():
        return {}
    raw = read_json(USER_INFO_PATH)
    users = raw.get("users")
    return users if isinstance(users, dict) else {}


def run_attachment_lambda(user_id: str, payloads: list[dict[str, Any]], *, allow_s3_result: bool) -> dict[str, Any]:
    if str(LAMBDA_DIR) not in sys.path:
        sys.path.insert(0, str(LAMBDA_DIR))
    if not allow_s3_result:
        os.environ.pop("MEWI_REPORT_RESULTS_BUCKET", None)
    os.environ["MEWI_REPORT_ATTACHMENT_MODE"] = "off"

    import handler as attachment_handler

    # Local S3-free equivalent of config/user_info.json.
    attachment_handler._USER_INFO_CACHE = load_user_info()
    result = attachment_handler.handler({
        "user_id": user_id,
        "sessions": payloads,
        "attachment_mode": "off",
    })
    if not isinstance(result, dict):
        raise RuntimeError("attachment-report handler did not return a JSON object")
    return result


def write_report(report_id: str, report: dict[str, Any]) -> None:
    for directory in (PROCESSED_DIR, STATIC_DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"report_{safe_segment(report_id)}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(REPORT_ROOT)}")


def safe_segment(value: object, fallback: str = "report") -> str:
    raw = str(value or fallback).strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")
    return cleaned or fallback


def load_report_routes(data_dir: Path) -> list[dict[str, str]]:
    loaded: list[dict[str, Any]] = []
    for path in sorted(data_dir.glob("report_*.json")):
        data_file_id = path.name[len("report_"):-len(".json")]
        try:
            report = read_json(path)
        except Exception:
            report = {}
        loaded.append({"dataFileId": data_file_id, "report": report})

    base_counts: dict[str, int] = {}
    for item in loaded:
        base = preferred_route_base(item)
        base_counts[base] = base_counts.get(base, 0) + 1

    base_ranks: dict[str, int] = {}
    used: set[str] = set()
    routes: list[dict[str, str]] = []
    for item in loaded:
        base = preferred_route_base(item)
        rank = base_ranks.get(base, 0) + 1
        base_ranks[base] = rank
        route_id = f"{base}_{rank}" if base_counts.get(base, 1) > 1 else base
        route_id = unique_route_id(route_id, used)
        routes.append({"dataFileId": item["dataFileId"], "routeId": route_id})
    return routes


def preferred_route_base(item: dict[str, Any]) -> str:
    report = item.get("report") if isinstance(item.get("report"), dict) else {}
    user = report.get("user") if isinstance(report.get("user"), dict) else {}
    return safe_segment(user.get("handle") or user.get("report_slug") or report.get("user_id") or item["dataFileId"], item["dataFileId"])


def unique_route_id(candidate: str, used: set[str]) -> str:
    route_id = candidate
    index = 2
    while route_id in used:
        route_id = f"{candidate}_{index}"
        index += 1
    used.add(route_id)
    return route_id


def print_summary(report_id: str, route_url: str, report: dict[str, Any]) -> None:
    meta = report.get("meta", {})
    signature = report.get("interaction_signature", {})
    action_counts = signature.get("action_counts", {}) if isinstance(signature, dict) else {}
    print("")
    print("Local E2E report ready")
    print(f"  report_id: {report_id}")
    print(f"  user_id:   {report.get('user_id', '')}")
    print(f"  sessions:  {meta.get('sessions', 0)}")
    print(f"  events:    {meta.get('total_events', 0)}")
    print(f"  actions:   {sum(int(value or 0) for value in action_counts.values())}")
    print(f"  route:     {route_url}")
    print("")
    print("Render it with:")
    print("  npm run dev")
    print(f"  open {route_url}")


def run_build() -> None:
    subprocess.run(["npm", "run", "build"], cwd=REPORT_ROOT, check=True)


def verify_render(route_url: str) -> None:
    try:
        with urllib.request.urlopen(route_url, timeout=15) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Could not fetch Astro route {route_url}. Is npm run dev/preview running?") from exc
    required = ("Player-cat action signature", "Attachment")
    missing = [text for text in required if text not in html]
    if missing:
        raise RuntimeError(f"Route fetched but missing expected text: {missing}")
    print(f"verified render: {route_url}")


if __name__ == "__main__":
    raise SystemExit(main())
