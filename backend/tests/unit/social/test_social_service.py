from app.social.service import SocialService
from app.world.state import WorldState


def _payload(zone: str, request_id: str = "t1") -> dict:
    return {
        "requestId": request_id,
        "place_context": {
            "current_zone_id": zone,
            "active_zone_ids": [zone],
            "reachable_zone_ids": [],
        },
        "self": {"location": {"x": 0.0, "y": 0.0, "z": 0.0}},
        "mood": {"social": 0.4},
        "action_result": {"status": "completed", "steps": []},
    }


async def test_alone_cat_produces_no_room_and_no_dialogue() -> None:
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("cat_mewi", _payload("Harbor.Dock"))

    result = await social.run_turn("cat_mewi")

    assert result.room is None
    assert result.delivered_inbox == []
    assert result.decision.spoke is False
    assert result.dialogue_for_unity() == []


async def test_two_cats_in_same_zone_open_one_room_and_speak_once() -> None:
    world = WorldState()
    social = SocialService(world=world)

    await world.ingest_tick("cat_mewi", _payload("Harbor.Dock"))
    await world.ingest_tick("cat_milo", _payload("Harbor.Dock"))

    # Mewi ticks first → notices Milo, transcript gets one line.
    first = await social.run_turn("cat_mewi")
    assert first.room is not None
    assert first.room.room_key == "cat_mewi,cat_milo"
    assert first.decision.spoke is True
    assert first.decision.utterance.speaker_id == "cat_mewi"
    assert first.delivered_inbox == []

    # Milo ticks next → consumes the pending utterance from Mewi.
    second = await social.run_turn("cat_milo")
    assert second.room is first.room  # same room object for the same set
    assert len(second.delivered_inbox) == 1
    assert second.delivered_inbox[0].utterance.speaker_id == "cat_mewi"
    assert second.decision.spoke is True

    # Relationship updated for the pair.
    rel = social.relationships_for("cat_mewi")
    assert len(rel) == 1
    assert rel[0].pair == ("cat_milo", "cat_mewi")
    assert rel[0].trust > 0
    assert rel[0].encounters >= 1


async def test_repeat_turn_by_same_speaker_stays_silent() -> None:
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("cat_a", _payload("Yard"))
    await world.ingest_tick("cat_b", _payload("Yard"))

    first = await social.run_turn("cat_a")
    second = await social.run_turn("cat_a")  # driver ticks twice without B replying

    assert first.decision.spoke is True
    assert second.decision.spoke is False
    assert second.decision.note == "recently spoke"


async def test_leaving_zone_dissolves_room_for_new_set() -> None:
    world = WorldState()
    social = SocialService(world=world)

    await world.ingest_tick("cat_a", _payload("Yard"))
    await world.ingest_tick("cat_b", _payload("Yard"))
    first = await social.run_turn("cat_a")
    assert first.room is not None
    first_key = first.room.room_key

    # Cat B moves to a different zone, then a new cat joins A.
    await world.ingest_tick("cat_b", _payload("Roof"))
    await world.ingest_tick("cat_c", _payload("Yard"))
    second = await social.run_turn("cat_a")

    assert second.room is not None
    assert second.room.room_key != first_key
    assert "cat_b" not in second.room.members
    assert "cat_c" in second.room.members
