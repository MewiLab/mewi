from unittest.mock import MagicMock

from app.agent.memory.memory_models import AspectMemory, RawMemoryEvent, TurnMemoryWrite
from app.repositories.supabase_memory_store import SupabaseMemoryStore


def _turn_memory(text: str = "The cat has recently chosen quiet actions.") -> TurnMemoryWrite:
    return TurnMemoryWrite(
        raw_event=RawMemoryEvent(
            creature_id="cat",
            tick=7,
            request_id="r7",
            source="python",
            event_type="memory_consolidation",
            payload={},
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
                aspect="action",
                text=text,
                tick=7,
                salience=0.6,
                memory_kind="summary",
                evidence={"source_count": 6, "tick_start": 1, "tick_end": 7},
            ),
        ],
    )


def _builder(data=None):
    builder = MagicMock()
    for method in ("select", "eq", "ilike", "order", "limit", "insert", "update"):
        getattr(builder, method).return_value = builder
    builder.execute.return_value = MagicMock(data=data or [])
    return builder


async def test_record_turn_reconciles_and_inserts_summary_rows_only() -> None:
    candidate_builder = _builder([])
    insert_builder = _builder([{"id": "summary-1"}])
    db = MagicMock()
    db.table.side_effect = [candidate_builder, insert_builder]

    await SupabaseMemoryStore(db).record_turn(_turn_memory())

    assert db.table.call_args_list[0].args[0] == "agent_memory_summaries"
    assert db.table.call_args_list[1].args[0] == "agent_memory_summaries"
    candidate_builder.eq.assert_any_call("creature_id", "cat")
    candidate_builder.eq.assert_any_call("is_active", True)
    candidate_builder.eq.assert_any_call("aspect", "action")

    rows = insert_builder.insert.call_args_list[0].args[0]
    assert len(rows) == 1
    row = rows[0]
    assert row["creature_id"] == "cat"
    assert row["memory_kind"] == "summary"
    assert row["aspect"] == "action"
    assert row["tick_start"] == 1
    assert row["tick_end"] == 7
    assert row["source_count"] == 6
    assert row["is_active"] is True
    assert row["last_active_tick"] == 7


async def test_record_turn_noops_and_reinforces_duplicate_summary() -> None:
    existing = {
        "id": "summary-old",
        "text": "The cat has recently chosen quiet actions.",
        "salience": 0.8,
        "tick_end": 5,
    }
    candidate_builder = _builder([existing])
    update_builder = _builder([existing])
    db = MagicMock()
    db.table.side_effect = [candidate_builder, update_builder]

    await SupabaseMemoryStore(db).record_turn(_turn_memory())

    assert update_builder.update.call_args_list
    patch = update_builder.update.call_args_list[0].args[0]
    assert patch["last_active_tick"] == 7
    assert patch["salience"] > 0.8
    update_builder.eq.assert_called_with("id", "summary-old")


async def test_search_filters_active_rows_and_reinforces_recall() -> None:
    row = {
        "id": "summary-1",
        "text": "cat napped in the kitchen",
        "aspect": "action",
        "tick_end": 7,
        "last_active_tick": 7,
        "salience": 0.4,
    }
    search_builder = _builder([row])
    update_builder = _builder([row])
    db = MagicMock()
    db.table.side_effect = [search_builder, update_builder]

    rows = await SupabaseMemoryStore(db).search(
        "kitchen",
        creature_id="cat",
        limit=5,
        now_tick=12,
    )

    assert db.table.call_args_list[0].args[0] == "agent_memory_summaries"
    search_builder.eq.assert_any_call("creature_id", "cat")
    search_builder.eq.assert_any_call("is_active", True)
    search_builder.ilike.assert_called_once_with("text", "%kitchen%")
    search_builder.order.assert_called_once_with("tick_end", desc=True)
    assert rows[0]["text"] == "cat napped in the kitchen"
    assert "score" in rows[0]

    patch = update_builder.update.call_args_list[0].args[0]
    assert patch["last_active_tick"] == 12
    assert patch["salience"] > 0.4


async def test_search_uses_vector_rpc_when_embedder_is_available() -> None:
    rpc_builder = MagicMock()
    rpc_builder.execute.return_value = MagicMock(
        data=[
            {
                "id": "summary-1",
                "text": "cat napped near the warm kitchen",
                "aspect": "action",
                "similarity": 0.91,
                "tick_end": 7,
                "salience": 0.4,
            }
        ]
    )
    update_builder = _builder([])
    db = MagicMock()
    db.rpc.return_value = rpc_builder
    db.table.return_value = update_builder

    rows = await SupabaseMemoryStore(
        db,
        embed_text=lambda text: [0.1] * 1536,
    ).search("warm kitchen", creature_id="cat", limit=3, now_tick=9)

    assert rows[0]["similarity"] == 0.91
    db.rpc.assert_called_once()
    name, params = db.rpc.call_args.args
    assert name == "match_agent_memory_summaries"
    assert params["match_creature_id"] == "cat"
    assert params["match_count"] == 3
    assert len(params["query_embedding"]) == 1536
