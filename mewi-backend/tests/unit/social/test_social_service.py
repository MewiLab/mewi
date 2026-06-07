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
    assert rel[0].pair == ("cat_mewi", "cat_milo")
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

    reply = await social.run_turn("cat_b")
    third = await social.run_turn("cat_a")
    assert reply.decision.spoke is True
    assert third.decision.spoke is False


async def test_agent_authored_line_is_routed_to_addressed_peer_only() -> None:
    world = WorldState()
    social = SocialService(world=world)
    for cid in ("cat_a", "cat_b", "cat_c"):
        await world.ingest_tick(cid, _payload("Yard"))

    spoke = await social.publish_turn(
        "cat_a",
        say="psst, over here",
        target="cat_b",
        expects_reply=True,
    )
    assert spoke.decision.spoke is True
    assert spoke.decision.utterance.speaker_id == "cat_a"
    assert spoke.decision.utterance.text == "psst, over here"
    assert spoke.decision.utterance.target_id == "cat_b"
    assert spoke.decision.utterance.bid_id

    # Only the addressed cat hears a targeted line.
    heard_b = await social.observe_turn("cat_b")
    heard_c = await social.observe_turn("cat_c")
    assert [i.utterance.text for i in heard_b.delivered_inbox] == ["psst, over here"]
    assert heard_b.delivered_inbox[0].to_prompt_context()["bid_id"]
    assert heard_c.delivered_inbox == []

    rel = social.relationships_for("cat_a")
    assert any(r.pair == ("cat_a", "cat_b") and r.trust > 0 for r in rel)


async def test_agent_line_without_target_is_heard_by_whole_room() -> None:
    world = WorldState()
    social = SocialService(world=world)
    for cid in ("cat_a", "cat_b", "cat_c"):
        await world.ingest_tick(cid, _payload("Yard"))

    await social.publish_turn("cat_a", say="hello everyone")

    heard_b = await social.observe_turn("cat_b")
    heard_c = await social.observe_turn("cat_c")
    assert len(heard_b.delivered_inbox) == 1
    assert len(heard_c.delivered_inbox) == 1


async def test_silent_cat_falls_back_to_low_rate_moderator_beat() -> None:
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("cat_a", _payload("Yard"))
    await world.ingest_tick("cat_b", _payload("Yard"))

    first = await social.publish_turn("cat_a")  # no words → ambient greeting
    second = await social.publish_turn("cat_a")  # still silent → stays quiet

    assert first.decision.spoke is True
    assert first.decision.note != "agent_spoke"
    assert second.decision.spoke is False
    assert second.decision.note == "recently spoke"


async def test_observe_turn_listens_without_authoring() -> None:
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("cat_a", _payload("Yard"))
    await world.ingest_tick("cat_b", _payload("Yard"))

    observed = await social.observe_turn("cat_a")
    assert observed.room is not None
    assert observed.decision.spoke is False
    assert observed.decision.note == "listening"
    # Listening alone must not put anything in cat_b's inbox.
    assert await social.observe_turn("cat_b") and social.transcript_for_room(
        observed.room.room_key
    ) == []


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


async def test_affordance_target_alias_resolves_to_room_member() -> None:
    # ADR-039: Unity affordance id "kosto_cat" must route to room member "kosto".
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("kosto", _payload("Yard"))
    await world.ingest_tick("miso", _payload("Yard"))

    spoke = await social.publish_turn(
        "miso",
        say="Fish smell is near the boxes.",
        target="kosto_cat",
        expects_reply=True,
    )
    assert spoke.decision.utterance.target_id == "kosto"

    heard = await social.observe_turn("kosto")
    assert [i.utterance.text for i in heard.delivered_inbox] == ["Fish smell is near the boxes."]


async def test_repeated_say_is_suppressed_as_body_language() -> None:
    # ADR-039 anti-loop: do not re-publish the speaker's own recent line.
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("kosto", _payload("Yard"))
    await world.ingest_tick("miso", _payload("Yard"))

    first = await social.publish_turn("miso", say="Sit here; the boardwalk is warm.")
    second = await social.publish_turn("miso", say="Sit here; the boardwalk is warm.")

    assert first.decision.spoke is True
    assert second.decision.note != "agent_spoke"


async def test_bid_outcome_matches_aliased_target_to_sender() -> None:
    # ADR-039: replying toward "kosto_cat" closes a bid raised by "kosto".
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("kosto", _payload("Yard"))
    await world.ingest_tick("miso", _payload("Yard"))

    await social.publish_turn("kosto", say="You heard that too?", target="miso", expects_reply=True)
    heard = await social.observe_turn("miso")
    delivered = [item.to_prompt_context() for item in heard.delivered_inbox]

    outcomes = social.resolve_observed_bids(
        "miso",
        delivered_inbox=delivered,
        selected_intent="SOCIALIZE",
        target_id="kosto_cat",
        spoke=True,
    )

    assert outcomes and outcomes[0]["status"] == "replied"


async def test_social_bid_feedback_arrives_on_sender_later_tick() -> None:
    world = WorldState()
    social = SocialService(world=world)
    await world.ingest_tick("cat_a", _payload("Yard"))
    await world.ingest_tick("cat_b", _payload("Yard"))

    await social.publish_turn(
        "cat_a",
        say="come look",
        target="cat_b",
        expects_reply=True,
    )
    heard = await social.observe_turn("cat_b")
    delivered = [item.to_prompt_context() for item in heard.delivered_inbox]

    outcomes = social.resolve_observed_bids(
        "cat_b",
        delivered_inbox=delivered,
        selected_intent="EXPLORE",
        target_id="garden",
        spoke=False,
    )

    assert outcomes[0]["status"] == "ignored"

    feedback = await social.observe_turn("cat_a")
    assert feedback.social_feedback
    assert feedback.social_feedback[0].outcome == "ignored"
    assert feedback.social_feedback[0].from_id == "cat_b"
