from app.world.state import WorldState


def _snapshot(zone: str, request_id: str = "t1", step_action: str = "go_to") -> dict:
    return {
        "requestId": request_id,
        "place_context": {
            "current_zone_id": zone,
            "active_zone_ids": [zone],
            "reachable_zone_ids": [],
        },
        "self": {"location": {"x": 1.0, "y": 0.0, "z": 2.5}},
        "mood": {"social": 0.5, "fear": 0.1},
        "action_result": {
            "status": "completed",
            "steps": [
                {"action": step_action, "target": "SM_Fish_1", "status": "completed", "reason": "Arrived"},
            ],
        },
    }


async def test_ingest_tick_records_zone_and_last_action() -> None:
    world = WorldState()

    presence = await world.ingest_tick("cat_001", _snapshot("Harbor.Dock"))

    assert presence.creature_id == "cat_001"
    assert presence.zone_id == "Harbor.Dock"
    assert presence.approx_xy == (1.0, 2.5)
    assert presence.last_action == "go_to"
    assert presence.last_action_target == "SM_Fish_1"
    assert presence.mood == {"social": 0.5, "fear": 0.1}


async def test_cats_in_zone_excludes_self_and_filters_zone() -> None:
    world = WorldState()
    await world.ingest_tick("cat_001", _snapshot("Harbor.Dock"))
    await world.ingest_tick("cat_002", _snapshot("Harbor.Dock"))
    await world.ingest_tick("cat_003", _snapshot("East_Roof"))

    snap = world.snapshot()
    peers = snap.cats_in_zone("Harbor.Dock", exclude="cat_001")
    peer_ids = sorted(p.creature_id for p in peers)

    assert peer_ids == ["cat_002"]
    assert snap.cats_in_zone("East_Roof") == [snap.cats["cat_003"]]
    assert snap.cats_in_zone("") == []


async def test_step_events_buffered_for_recent_reads() -> None:
    world = WorldState(event_buffer=4)

    await world.ingest_tick("cat_001", _snapshot("Harbor.Dock", step_action="go_to"))
    await world.ingest_tick("cat_001", _snapshot("Harbor.Dock", step_action="eat"))

    events = world.recent_events()
    assert [event["action"] for event in events] == ["go_to", "eat"]
    assert events[-1]["creature_id"] == "cat_001"
