from langchain_core.messages import AIMessage

from app.agent.memory import memory_consolidate
from app.agent.memory.memory_manager import MemoryManager
from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent


class FakeStore:
    def __init__(self) -> None:
        self.writes = []

    async def record_turn(self, write) -> None:
        self.writes.append(write)

    async def search(
        self,
        query: str,
        *,
        creature_id: str,
        limit: int = 5,
        now_tick: int | None = None,
    ):
        return []


class FakeLLM:
    """Returns a fixed recap and counts how often it is asked."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages, **kwargs) -> AIMessage:
        self.calls += 1
        return AIMessage(content="Recap: greeted the other cats and stayed close.")


def _fill(mem: MemoryManager, aspect: str, count: int) -> None:
    for tick in range(count):
        mem.record_short_term(
            AspectMemory(aspect=aspect, text=f"{aspect} line {tick}", tick=tick, salience=0.4)
        )


async def test_consolidation_folds_old_entries_into_one_summary() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    _fill(mem, "action", 8)

    folded = await mem.consolidate(llm, threshold=6, keep_recent=2)

    assert folded == 1
    assert llm.calls == 1
    bucket = list(mem._short_term["action"])
    # one summary at the front + the two most-recent verbatim entries
    assert len(bucket) == 3
    assert bucket[0].memory_kind == "summary"
    assert bucket[0].evidence["consolidated_from"] == 6
    assert [m.text for m in bucket[1:]] == ["action line 6", "action line 7"]


async def test_under_threshold_does_not_call_llm() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    _fill(mem, "action", 5)

    folded = await mem.consolidate(llm, threshold=6, keep_recent=2)

    assert folded == 0
    assert llm.calls == 0
    assert len(mem._short_term["action"]) == 5


async def test_entries_appended_during_summary_are_preserved(monkeypatch) -> None:
    mem = MemoryManager()
    _fill(mem, "action", 8)

    # Simulate a new memory landing while the (awaited) LLM call is in flight.
    original = memory_consolidate.consolidate_aspect_llm

    async def racing_consolidate(llm, aspect, memories):
        mem.record_short_term(
            AspectMemory(aspect="action", text="late arrival", tick=99, salience=0.4)
        )
        return await original(llm, aspect, memories)

    monkeypatch.setattr(memory_consolidate, "consolidate_aspect_llm", racing_consolidate)
    await mem.consolidate(FakeLLM(), threshold=6, keep_recent=2)

    texts = [m.text for m in mem._short_term["action"]]
    assert "late arrival" in texts  # not lost in the swap
    assert texts[0].startswith("Recap")  # summary still at the front


async def test_consolidation_persists_only_summary_write() -> None:
    store = FakeStore()
    mem = MemoryManager(store=store)
    mem.record_raw_event(
        RawMemoryEvent(
            creature_id="cat",
            tick=7,
            request_id="r7",
            source="python",
            event_type="planning_turn",
            payload={},
        )
    )
    _fill(mem, "action", 8)

    folded = await mem.consolidate(FakeLLM(), threshold=6, keep_recent=2)

    assert folded == 1
    assert len(store.writes) == 1
    write = store.writes[0]
    assert write.raw_event.event_type == "memory_consolidation"
    assert [memory.memory_kind for memory in write.aspect_memories] == ["summary"]
    summary = write.aspect_memories[0]
    assert summary.evidence["source_count"] == 6
    assert summary.evidence["tick_start"] == 0
    assert summary.evidence["tick_end"] == 5
