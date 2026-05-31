from typing import Any

from app.agent.memory.memory_manager import MemoryManager
from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent, TurnMemoryWrite
from app.services.memory.memory_service import MemoryService


def _turn_memory() -> TurnMemoryWrite:
    return TurnMemoryWrite(
        raw_event=RawMemoryEvent(
            creature_id="cat",
            tick=3,
            request_id="r3",
            source="python",
            event_type="planning_turn",
            payload={"intent": "EXPLORE"},
        ),
        aspect_memories=[
            AspectMemory(
                aspect="action",
                text="The cat planned a careful explore.",
                tick=3,
                salience=0.5,
                memory_kind="episodic",
            )
        ],
    )


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[TurnMemoryWrite] = []

    def save_turn_memory(self, write: TurnMemoryWrite) -> dict[str, Any]:
        self.saved.append(write)
        return {"raw_event": {"id": "raw-1"}, "short_term_memories": []}


class FailingStore:
    def save_turn_memory(self, write: TurnMemoryWrite) -> dict[str, Any]:
        raise RuntimeError("database unavailable")


def test_record_turn_memory_updates_hot_memory_and_store() -> None:
    memory = MemoryManager()
    store = FakeStore()

    result = MemoryService(store).record_turn_memory(memory, _turn_memory())

    assert memory.raw_event_count == 1
    assert memory.short_term_count == 1
    assert store.saved[0].raw_event.creature_id == "cat"
    assert result["persisted"] is True


def test_record_turn_memory_keeps_hot_memory_when_store_fails() -> None:
    memory = MemoryManager()

    result = MemoryService(FailingStore()).record_turn_memory(memory, _turn_memory())

    assert memory.raw_event_count == 1
    assert memory.short_term_count == 1
    assert result == {"persisted": False, "reason": "store_error"}
