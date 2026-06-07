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
        self.prompts: list[str] = []

    async def ainvoke(self, messages, **kwargs) -> AIMessage:
        self.calls += 1
        self.prompts.append(messages[0].content)
        return AIMessage(content="Recap: greeted the other cats and stayed close.")


def _fill(mem: MemoryManager, aspect: str, count: int) -> None:
    for tick in range(count):
        mem.record_short_term(
            AspectMemory(aspect=aspect, text=f"{aspect} line {tick}", tick=tick, salience=0.4)
        )


def _raw_turns(mem: MemoryManager, count: int) -> None:
    for tick in range(count):
        mem.record_raw_event(
            RawMemoryEvent(
                creature_id="cat",
                tick=tick,
                request_id=f"r{tick}",
                source="python",
                event_type="planning_turn",
                payload={},
            )
        )


async def test_consolidation_folds_old_entries_into_one_summary() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    _fill(mem, "action", 8)

    folded = await mem.consolidate(llm, threshold=6, keep_recent=2, min_turns=0)

    assert folded == 1
    assert llm.calls == 1
    assert [m.text for m in mem._short_term["action"]] == ["action line 6", "action line 7"]
    summary_bucket = list(mem._short_term["reflection"])
    assert len(summary_bucket) == 1
    assert summary_bucket[0].memory_kind == "summary"
    assert summary_bucket[0].evidence["consolidated_from"] == 6
    assert summary_bucket[0].evidence["source_count"] == 8


async def test_under_threshold_does_not_call_llm() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    _fill(mem, "action", 5)

    folded = await mem.consolidate(llm, threshold=6, keep_recent=2, min_turns=0)

    assert folded == 0
    assert llm.calls == 0
    assert len(mem._short_term["action"]) == 5


async def test_entries_appended_during_summary_are_preserved(monkeypatch) -> None:
    mem = MemoryManager()
    _fill(mem, "action", 8)

    # Simulate a new memory landing while the (awaited) LLM call is in flight.
    original = memory_consolidate.consolidate_memory_llm

    async def racing_consolidate(llm, memories, *, related_memories=None):
        mem.record_short_term(
            AspectMemory(aspect="action", text="late arrival", tick=99, salience=0.4)
        )
        return await original(llm, memories, related_memories=related_memories)

    monkeypatch.setattr(memory_consolidate, "consolidate_memory_llm", racing_consolidate)
    await mem.consolidate(FakeLLM(), threshold=6, keep_recent=2, min_turns=0)

    texts = [m.text for items in mem._short_term.values() for m in items]
    assert "late arrival" in texts  # not lost in the swap
    assert any(text.startswith("Recap") for text in texts)


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

    folded = await mem.consolidate(FakeLLM(), threshold=6, keep_recent=2, min_turns=0)

    assert folded == 1
    assert len(store.writes) == 1
    write = store.writes[0]
    assert write.raw_event.event_type == "memory_consolidation"
    assert [memory.memory_kind for memory in write.aspect_memories] == ["summary"]
    summary = write.aspect_memories[0]
    assert summary.aspect == "reflection"
    assert summary.evidence["source_count"] == 8
    assert summary.evidence["tick_start"] == 0
    assert summary.evidence["tick_end"] == 5


async def test_consolidation_waits_for_min_python_turns() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    _fill(mem, "action", 8)
    _raw_turns(mem, 3)

    folded = await mem.consolidate(llm, threshold=6, keep_recent=2, min_turns=10)

    assert folded == 0
    assert llm.calls == 0


async def test_default_consolidation_uses_python_turn_count() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    _fill(mem, "action", 8)
    _raw_turns(mem, 10)

    folded = await mem.consolidate(llm)

    assert folded == 1
    summary = list(mem._short_term["reflection"])[0]
    assert summary.evidence["source_count"] == 8
    assert summary.evidence["summary_style"] == "reflective"


async def test_consolidation_prompt_requests_reflection_and_related_memory() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    _fill(mem, "action", 8)

    await mem.consolidate(
        llm,
        min_turns=0,
        related_memories=[{"aspect": "social", "text": "The cat remembers Haru nearby."}],
    )

    assert llm.prompts
    assert "reflective long-term memory" in llm.prompts[0]
    assert "SHORT-TERM MEMORY" in llm.prompts[0]
    assert "RELATED LONG-TERM MEMORY" in llm.prompts[0]
    assert "CURRENT INTENTION" in llm.prompts[0]
    assert "The cat remembers Haru nearby." in llm.prompts[0]


async def test_consolidation_prompt_hoists_newest_action_intention() -> None:
    mem = MemoryManager()
    llm = FakeLLM()
    for tick in range(8):
        intent = "SEEK_FOOD" if tick < 5 else "REST"
        mem.record_short_term(
            AspectMemory(
                aspect="action",
                text=f"action line {tick}. Current intention: {intent} near a mackerel.",
                tick=tick,
                salience=0.4,
                evidence={"intent": intent},
            )
        )

    await mem.consolidate(llm, threshold=6, keep_recent=2, min_turns=0)

    assert llm.prompts
    prompt = llm.prompts[0]
    intention_block = prompt.split("CURRENT INTENTION", 1)[1].split("SHORT-TERM MEMORY", 1)[0]
    # The newest consolidated action carries REST, not the repeated SEEK_FOOD.
    assert "REST" in intention_block
    assert "SEEK_FOOD" not in intention_block
