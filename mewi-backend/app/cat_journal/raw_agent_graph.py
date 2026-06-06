from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL_DIR = Path(__file__).resolve().parent / "journal"
RAW_GRAPH_FILENAME = "raw_agent_graph.jsonl"
LIVE_MICRO_ACTION_FILENAME = "live_micro_actions.jsonl"

_SAFE_PATH_PART = re.compile(r"[^A-Za-z0-9_.-]+")
_OMITTED_GRAPH_KEYS = {"messages", "runtime", "raw_payload"}


class RawCatJournal:
    """Append-only local journal for backend-owned cat decision turns.

    Each creature gets one JSONL file:

        app/cat_journal/journal/<creature_id>/raw_agent_graph.jsonl

    The records are intentionally raw enough for later processing, but omit
    non-serializable runtime objects and LangChain message objects.
    """

    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = _resolve_root(root_dir)

    @classmethod
    def from_settings(cls, settings: Any) -> "RawCatJournal":
        return cls(getattr(settings, "cat_journal_dir", None))

    async def append_graph_turn(
        self,
        *,
        creature_id: str,
        job: dict[str, Any],
        unity_payload: dict[str, Any],
        graph_state: dict[str, Any],
        unity_result: dict[str, Any],
    ) -> Path:
        record = self.build_record(
            creature_id=creature_id,
            job=job,
            unity_payload=unity_payload,
            graph_state=graph_state,
            unity_result=unity_result,
        )
        path = self.path_for(creature_id)
        await asyncio.to_thread(_append_jsonl, path, record)
        return path

    async def append_micro_action_events(
        self,
        *,
        creature_id: str,
        events: list[Any],
    ) -> Path:
        records = [
            self.build_micro_action_record(creature_id=creature_id, event=event)
            for event in events
        ]
        path = self.micro_action_path_for(creature_id)
        await asyncio.to_thread(_append_jsonl_many, path, records)
        return path

    def build_record(
        self,
        *,
        creature_id: str,
        job: dict[str, Any],
        unity_payload: dict[str, Any],
        graph_state: dict[str, Any],
        unity_result: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = (
            job.get("request_id")
            or unity_payload.get("requestId")
            or graph_state.get("request_id")
            or ""
        )
        tick = graph_state.get("tick", unity_payload.get("tick", 0))
        return {
            "schema_version": "raw_agent_graph.v1",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "creature_id": creature_id,
            "request_id": request_id,
            "tick": tick,
            "job": _jsonable({
                "job_id": job.get("job_id", ""),
                "status": job.get("status", ""),
                "queued_at": job.get("queued_at", ""),
            }),
            "unity_payload": _jsonable(unity_payload),
            "graph_state": _jsonable(_decision_graph_state(graph_state)),
            "unity_result": _jsonable(unity_result),
        }

    def build_micro_action_record(
        self,
        *,
        creature_id: str,
        event: Any,
    ) -> dict[str, Any]:
        payload = _jsonable(event)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return {
            "schema_version": "mewi.live_micro_action.v1",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "creature_id": creature_id or payload.get("creature_id", ""),
            "event_id": payload.get("event_id", ""),
            "correlation_id": payload.get("correlation_id", ""),
            "tick": payload.get("tick", 0),
            "request_id": payload.get("request_id", ""),
            "event": payload,
        }

    def path_for(self, creature_id: str) -> Path:
        return self.root_dir / _safe_creature_dir(creature_id) / RAW_GRAPH_FILENAME

    def micro_action_path_for(self, creature_id: str) -> Path:
        return self.root_dir / _safe_creature_dir(creature_id) / LIVE_MICRO_ACTION_FILENAME


def _resolve_root(root_dir: str | Path | None) -> Path:
    if root_dir is None or str(root_dir).strip() == "":
        return DEFAULT_JOURNAL_DIR
    path = Path(root_dir).expanduser()
    return path if path.is_absolute() else BACKEND_DIR / path


def _safe_creature_dir(creature_id: str) -> str:
    cleaned = _SAFE_PATH_PART.sub("_", str(creature_id or "").strip()).strip("._-")
    return cleaned[:96] or "unknown_cat"


def _decision_graph_state(graph_state: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in graph_state.items()
        if key not in _OMITTED_GRAPH_KEYS
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json"))
        except TypeError:
            return _jsonable(model_dump())
    to_prompt_context = getattr(value, "to_prompt_context", None)
    if callable(to_prompt_context):
        return _jsonable(to_prompt_context())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    return repr(value)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    _append_jsonl_many(path, [record])


def _append_jsonl_many(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for record in records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            file.write(line)
            file.write("\n")
