from unittest.mock import MagicMock

from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent, TurnMemoryWrite
from app.repositories.memory_repo import MemoryRepository


def _turn_memory() -> TurnMemoryWrite:
    return TurnMemoryWrite(
        raw_event=RawMemoryEvent(
            creature_id="cat",
            tick=7,
            request_id="r7",
            source="python",
            event_type="planning_turn",
            payload={"plan_steps": [{"action": "sit"}]},
        ),
        aspect_memories=[
            AspectMemory(
                aspect="action",
                text="The cat chose to sit.",
                tick=7,
                salience=0.4,
                memory_kind="episodic",
                evidence={"intent": "IDLE"},
            ),
            AspectMemory(
                aspect="body",
                text="Energy is low.",
                tick=7,
                salience=0.6,
                memory_kind="working",
            ),
        ],
    )


def test_save_turn_memory_persists_raw_then_short_term_rows() -> None:
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.execute.side_effect = [
        MagicMock(data=[{"id": "raw-memory-id"}]),
        MagicMock(data=[{"id": "short-1"}, {"id": "short-2"}]),
    ]
    db = MagicMock()
    db.table.return_value = builder

    result = MemoryRepository(db).save_turn_memory(_turn_memory())

    assert db.table.call_args_list[0].args[0] == "agent_memory_raw_events"
    assert db.table.call_args_list[1].args[0] == "agent_short_term_memories"

    raw_row = builder.insert.call_args_list[0].args[0]
    assert raw_row["creature_id"] == "cat"
    assert raw_row["event_type"] == "planning_turn"
    assert raw_row["payload"]["plan_steps"][0]["action"] == "sit"

    short_rows = builder.insert.call_args_list[1].args[0]
    assert [row["memory_kind"] for row in short_rows] == ["episodic", "working"]
    assert all(row["raw_event_id"] == "raw-memory-id" for row in short_rows)
    assert result["raw_event"]["id"] == "raw-memory-id"
