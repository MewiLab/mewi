"""Reprocess already-stored raw sessions into a processed report (no POST).

Use after dropping raw session files straight into
``pipeline/raw_data/sessions/<user_id>/`` by hand: this runs the *same*
``process_report`` derivation that the ingest route triggers
(``InlineProcessingTrigger``), then writes ``report_<user_id>.json`` to
``pipeline/processed_data`` and the Astro site's ``src/data``.

It reuses the same env-driven paths as ``app/api/deps.py`` and
``attachment_client.py`` (``MEWI_REPORT_*``), so this is just the ingest
trigger without the HTTP layer.

Usage (from mewi-backend/, with the project venv):
    python -m app.services.report.reprocess --user vanillaSky00
    MEWI_REPORT_ATTACHMENT_MODE=default \\
        python -m app.services.report.reprocess --user vanillaSky00

Default attachment mode is the Claude Agent SDK skill. Set
``MEWI_REPORT_ATTACHMENT_MODE=default`` to force the deterministic fallback
without an API call.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.services.report.attachment_client import (
    PIPELINE_DIR,
    PROCESSED_DIR,
    REPORT_ROOT,
    SESSIONS_DIR,
    _env_path,
)
from app.services.report.store import (
    LocalFileProcessedReportStore,
    LocalFileRawSessionStore,
    LocalFileReportSources,
    safe_segment,
)
from app.services.report.trigger import InlineProcessingTrigger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reprocess stored raw sessions into a processed report (no POST).",
    )
    parser.add_argument(
        "--user",
        required=True,
        help="user_id / slug folder under raw_data/sessions/ (e.g. vanillaSky00).",
    )
    args = parser.parse_args(argv)

    site_data_dir = _env_path("MEWI_REPORT_SITE_DATA_DIR", REPORT_ROOT / "src" / "data")
    user_info_path = _env_path("MEWI_REPORT_USER_INFO", PIPELINE_DIR / "user_info.json")
    overrides_dir = _env_path("MEWI_REPORT_OVERRIDES_DIR", PIPELINE_DIR / "report_overrides")
    attachment_mode = os.getenv("MEWI_REPORT_ATTACHMENT_MODE", "agent").strip() or "agent"

    raw_store = LocalFileRawSessionStore(SESSIONS_DIR)
    count = raw_store.count(args.user)
    if count == 0:
        print(
            f"error: no raw sessions for '{args.user}' under {SESSIONS_DIR}",
            file=sys.stderr,
        )
        return 1

    processed_store = LocalFileProcessedReportStore(PROCESSED_DIR, site_data_dir)
    sources = LocalFileReportSources(user_info_path, overrides_dir)
    trigger = InlineProcessingTrigger(raw_store, processed_store, sources, attachment_mode)

    if not trigger.maybe_run(args.user, count):
        print(f"error: processing produced no report for '{args.user}'", file=sys.stderr)
        return 1

    name = f"report_{safe_segment(args.user)}.json"
    print(f"processed {count} session(s) for '{args.user}' (attachment_mode={attachment_mode})")
    print(f"  -> {PROCESSED_DIR / name}")
    print(f"  -> {site_data_dir / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
