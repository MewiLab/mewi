"""Storage ports for the report pipeline.

These are the only abstractions ADR-014 allows: small ``Protocol`` ports that
hide *where* raw sessions, processed reports, and report context live. Today
everything is local files under ``mewi-report/``. Later, ``RawSessionStore`` and
``ProcessedReportStore`` can become S3-backed without touching the route or the
service orchestration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol


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


# ── processed report store ────────────────────────────────────────────────────

class ProcessedReportStore(Protocol):
    def write(self, user_id: str, report: dict[str, Any]) -> list[str]: ...


class LocalFileProcessedReportStore:
    """Writes ``report_{user_id}.json`` to the pipeline output and the Astro site.

    Mirrors what ``mewi-report/pipeline/scripts/process.py`` used to do at the end
    of a run: write to ``processed_data/`` and copy into ``src/data/`` so the
    static site can import it at build time.
    """

    def __init__(self, processed_dir: Path, site_data_dir: Path) -> None:
        self._processed_dir = processed_dir
        self._site_data_dir = site_data_dir

    def write(self, user_id: str, report: dict[str, Any]) -> list[str]:
        payload = json.dumps(report, indent=2, ensure_ascii=False)
        written: list[str] = []
        for directory in (self._processed_dir, self._site_data_dir):
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"report_{safe_segment(user_id)}.json"
            tmp_path = path.with_suffix(".json.tmp")
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(path)
            written.append(str(path))
        return written


# ── report context (user_info + demo overrides) ───────────────────────────────

class ReportSources(Protocol):
    def user_info(self) -> dict[str, dict[str, Any]]: ...
    def overrides(self, user_id: str) -> dict[str, Any]: ...


class LocalFileReportSources:
    """Reads ``pipeline/user_info.json`` and ``pipeline/report_overrides/{user}.json``."""

    def __init__(self, user_info_path: Path, overrides_dir: Path) -> None:
        self._user_info_path = user_info_path
        self._overrides_dir = overrides_dir

    def user_info(self) -> dict[str, dict[str, Any]]:
        raw = _read_json(self._user_info_path)
        if not raw:
            return {}
        users = raw.get("users")
        return users if isinstance(users, dict) else {}

    def overrides(self, user_id: str) -> dict[str, Any]:
        raw = _read_json(self._overrides_dir / f"{safe_segment(user_id)}.json")
        if not raw:
            return {}
        nested = raw.get("report_overrides")
        return nested if isinstance(nested, dict) else raw
