import json

from app.cat_journal.raw_agent_graph import RawCatJournal


async def test_append_graph_turn_writes_one_jsonl_record_per_cat(tmp_path):
    journal = RawCatJournal(tmp_path)

    path = await journal.append_graph_turn(
        creature_id="vanilla/Sky 00",
        job={
            "job_id": "job-1",
            "request_id": "req-1",
            "status": "queued",
            "queued_at": "2026-05-30T00:00:00+00:00",
        },
        unity_payload={
            "requestId": "req-1",
            "tick": 7,
            "action_result": {"status": "completed", "action": "go_to"},
        },
        graph_state={
            "tick": 7,
            "intent_decision": {"intent": "EXPLORE"},
            "plan_steps": [{"action": "smell", "target": None}],
            "action_result": {"status": "done", "action": "smell"},
            "messages": ["full prompts are intentionally omitted"],
            "runtime": object(),
            "raw_payload": {"duplicated": "unity_payload"},
        },
        unity_result={
            "request_id": "req-1",
            "tick": 7,
            "plan_steps": [{"action": "smell", "target": None}],
        },
    )

    assert path == tmp_path / "vanilla_Sky_00" / "raw_agent_graph.jsonl"

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["schema_version"] == "raw_agent_graph.v1"
    assert record["creature_id"] == "vanilla/Sky 00"
    assert record["request_id"] == "req-1"
    assert record["tick"] == 7
    assert record["unity_payload"]["action_result"]["status"] == "completed"
    assert record["graph_state"]["intent_decision"]["intent"] == "EXPLORE"
    assert "messages" not in record["graph_state"]
    assert "runtime" not in record["graph_state"]
    assert "raw_payload" not in record["graph_state"]
