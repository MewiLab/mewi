from app.agent.memory.memory_manager import MemoryManager
from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent
from app.agent.arbitration.helpers.life_balance import (
    compute_life_balance,
    life_balance_focus_lines,
)


def _serve(mem: MemoryManager, tick: int, intent: str) -> None:
    """Record one served intent both as a raw event and an STM action line."""
    mem.record_raw_event(
        RawMemoryEvent(
            creature_id="cat_a",
            tick=tick,
            request_id=f"r{tick}",
            source="python",
            event_type="planning_turn",
            payload={"intent_decision": {"intent": intent}},
        )
    )
    mem.record_short_term(
        AspectMemory(
            aspect="action",
            text=f"Next intent {intent} became plan: x.",
            tick=tick,
            salience=0.4,
        )
    )


def test_repeated_socializing_flags_curiosity_as_neglected() -> None:
    mem = MemoryManager()
    for tick in range(5):
        _serve(mem, tick, "SOCIALIZE")

    context = mem.recall(last_n=5).to_prompt_context()
    report = compute_life_balance(context)

    assert "curiosity" in report.neglected()
    assert any("explored" in hint.lower() for hint in life_balance_focus_lines(context))


def test_exploring_recently_clears_the_curiosity_hint() -> None:
    mem = MemoryManager()
    for tick in range(4):
        _serve(mem, tick, "SOCIALIZE")
    _serve(mem, 4, "EXPLORE")

    report = compute_life_balance(mem.recall(last_n=5).to_prompt_context())

    assert "curiosity" not in report.neglected()


def test_intent_history_survives_stm_text_consolidation() -> None:
    # After consolidation the STM `action` text is a summary with no
    # "Next intent" markers, but the raw-event trail still carries intents.
    mem = MemoryManager()
    for tick in range(5):
        _serve(mem, tick, "SOCIALIZE")

    mem._short_term["action"].clear()
    mem.record_short_term(
        AspectMemory(
            aspect="action",
            text="Recap: kept greeting the cats nearby.",
            tick=4,
            salience=0.5,
            memory_kind="summary",
        )
    )

    report = compute_life_balance(mem.recall(last_n=5).to_prompt_context())
    assert "curiosity" in report.neglected()
