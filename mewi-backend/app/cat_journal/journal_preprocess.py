from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.cat_journal.raw_agent_graph import DEFAULT_JOURNAL_DIR, RawCatJournal


PROCESSED_JOURNAL_FILENAME = "processed_journal.json"


def load_cat_records(
    creature_id: str,
    *,
    root_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load every JSONL journal record currently stored for one cat."""
    journal = RawCatJournal(root_dir)
    cat_dir = journal.path_for(creature_id).parent
    if not cat_dir.is_dir():
        raise FileNotFoundError(f"No journal directory for cat '{creature_id}': {cat_dir}")

    files = sorted(cat_dir.glob("*.jsonl"))
    if not files:
        raise FileNotFoundError(f"No JSONL journal files found for cat '{creature_id}': {cat_dir}")
    return load_records(files)


def load_records(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Load JSONL or JSON journal records from explicit files or directories."""
    records: list[dict[str, Any]] = []
    for item in paths:
        path = Path(item).expanduser()
        if path.is_dir():
            records.extend(load_records(sorted(path.glob("*.jsonl"))))
            continue
        if not path.exists():
            raise FileNotFoundError(f"Journal input not found: {path}")
        if path.suffix == ".jsonl":
            records.extend(_load_jsonl(path))
        else:
            records.extend(_coerce_records(json.loads(path.read_text(encoding="utf-8"))))
    return records


def preprocess_cat_journal(
    records: list[dict[str, Any]],
    *,
    creature_id: str | None = None,
) -> dict[str, Any]:
    """Condense raw agent graph records into a compact cat-life digest.

    The raw records preserve everything useful from the graph. This digest turns
    them into stable derived facts: intent/action mix, place changes, execution
    feedback from Unity, social rooms, dialogue, relationships, and memorable
    turns.
    """
    selected = [
        record
        for record in records
        if isinstance(record, dict)
        and (not creature_id or record.get("creature_id") in {None, "", creature_id})
    ]
    selected.sort(key=lambda item: (_int(item.get("tick")), _clean(item.get("recorded_at"))))

    cat_id = creature_id or _first_text(selected, "creature_id") or "unknown_cat"
    turns = [_turn_digest(record, cat_id) for record in selected]

    intent_counts = Counter(t["intent"]["name"] for t in turns if t["intent"]["name"])
    chosen_action_counts = Counter(
        t["chosen_action"]["action"] for t in turns if t["chosen_action"]["action"]
    )
    plan_action_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    place_counts = Counter(t["place"]["current_zone_id"] for t in turns if t["place"]["current_zone_id"])
    previous_status_counts = Counter(
        t["execution"]["previous_status"] for t in turns if t["execution"]["previous_status"]
    )

    for turn in turns:
        for step in turn["plan_steps"]:
            action = _clean(step.get("action"))
            target = _clean(step.get("target"))
            if action:
                plan_action_counts[action] += 1
            if target:
                target_counts[target] += 1

    social = _social_digest(turns, cat_id)
    memorable = _memorable_turns(turns)
    tick_values = [turn["tick"] for turn in turns if isinstance(turn["tick"], int)]
    statistics = _total_statistics(
        turns=turns,
        intent_counts=intent_counts,
        chosen_action_counts=chosen_action_counts,
        plan_action_counts=plan_action_counts,
        target_counts=target_counts,
        place_counts=place_counts,
        previous_status_counts=previous_status_counts,
        social=social,
    )

    return {
        "schema_version": "cat_journal_digest.v1",
        "creature_id": cat_id,
        "source": {
            "record_count": len(selected),
            "turn_count": len(turns),
            "tick_range": {
                "first": min(tick_values) if tick_values else None,
                "last": max(tick_values) if tick_values else None,
            },
            "recorded_at": {
                "first": _first_text(turns, "recorded_at"),
                "last": _last_text(turns, "recorded_at"),
            },
        },
        "mix": {
            "intents": _counter_items(intent_counts, len(turns)),
            "chosen_actions": _counter_items(chosen_action_counts, len(turns)),
            "plan_actions": _counter_items(plan_action_counts, sum(plan_action_counts.values())),
            "targets": _counter_items(target_counts, sum(target_counts.values())),
        },
        "mood": _numeric_series_digest([turn["mood"] for turn in turns]),
        "health": _numeric_series_digest([turn["health"] for turn in turns]),
        "places": {
            "visited": _counter_items(place_counts, len(turns)),
            "sequence": _compressed_sequence(
                turn["place"]["current_zone_id"] for turn in turns
            ),
        },
        "execution": {
            "previous_statuses": _counter_items(previous_status_counts, len(turns)),
            "problem_turns": [
                turn
                for turn in turns
                if turn["execution"]["previous_status"]
                and turn["execution"]["previous_status"]
                not in {"done", "completed", "success", "succeeded"}
            ][:20],
        },
        "social": social,
        "statistics": statistics,
        "memorable_turns": memorable,
        "turn_samples": _sample_turns(turns, memorable),
    }


def build_processed_journal(digest: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic processed journal when no agent is used."""
    creature_id = _clean(digest.get("creature_id")) or "unknown_cat"
    display = _display_name(creature_id)
    source = _dict(digest.get("source"))
    top_intents = _list(_dict(digest.get("mix")).get("intents"))
    top_actions = _list(_dict(digest.get("mix")).get("plan_actions"))
    social = _dict(digest.get("social"))
    statistics = _dict(digest.get("statistics"))
    relationships = _list(social.get("relationships"))
    memorable = _list(digest.get("memorable_turns"))

    return {
        "schema_version": "cat_journal.v1",
        "creature_id": creature_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "title": f"{display}'s Living Journal",
        "subtitle": _subtitle(source, top_intents, social),
        "portrait": {
            "one_line": _one_line(display, digest),
            "temperament": _temperament_tags(digest),
            "at_a_glance": _list(statistics.get("badges"))[:6],
            "signature_moves": [
                f"{item['name']} ({item['count']})" for item in top_actions[:5]
            ],
            "social_style": _social_style(social),
            "solitude_style": _solitude_style(digest),
        },
        "statistics": statistics,
        "arcs": _arcs(digest),
        "relationships": [
            _relationship_card(peer) for peer in relationships[:8]
        ],
        "episodes": [
            _episode_card(turn) for turn in memorable[:10]
        ],
        "patterns": {
            "intent_mix": top_intents,
            "action_mix": top_actions,
            "places": _dict(digest.get("places")).get("visited", []),
            "execution": _dict(digest.get("execution")).get("previous_statuses", []),
        },
        "open_threads": _open_threads(digest),
        "caveat": "This journal is a behavioral reading of backend graph logs, not a claim about an animal or player outside the simulation.",
    }


def processed_path_for(
    creature_id: str,
    *,
    root_dir: str | Path | None = None,
) -> Path:
    return RawCatJournal(root_dir).path_for(creature_id).parent / PROCESSED_JOURNAL_FILENAME


def write_processed_journal(
    creature_id: str,
    journal: dict[str, Any],
    *,
    root_dir: str | Path | None = None,
) -> Path:
    path = processed_path_for(creature_id, root_dir=root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _turn_digest(record: dict[str, Any], creature_id: str) -> dict[str, Any]:
    raw = _dict(record.get("unity_payload"))
    graph = _dict(record.get("graph_state"))
    result = _dict(record.get("unity_result"))
    memory_payload = _memory_payload(graph)

    intent = (
        _dict(graph.get("intent_decision"))
        or _dict(result.get("intent"))
        or _dict(memory_payload.get("intent_decision"))
    )
    plan_steps = (
        _list(graph.get("plan_steps"))
        or _list(result.get("plan_steps"))
        or _list(memory_payload.get("plan_steps"))
    )
    chosen = _dict(graph.get("chosen_action")) or _dict(memory_payload.get("chosen_action"))
    if not chosen and plan_steps:
        first = _dict(plan_steps[0])
        chosen = {"action": first.get("action"), "kwargs": {"target": first.get("target")}}

    social_context = (
        _dict(graph.get("social_context"))
        or _dict(result.get("social_context"))
        or _dict(memory_payload.get("social_context"))
    )
    dialogue = (
        _list(graph.get("dialogue"))
        or _list(result.get("dialogue"))
        or _list(memory_payload.get("dialogue"))
    )
    previous_result = _dict(raw.get("action_result")) or _dict(memory_payload.get("previous_action_result"))

    return {
        "tick": _int(record.get("tick", graph.get("tick", raw.get("tick")))),
        "recorded_at": _clean(record.get("recorded_at")),
        "request_id": _clean(record.get("request_id") or raw.get("requestId")),
        "intent": {
            "name": _clean(intent.get("intent")) or "IDLE",
            "target_id": _clean(intent.get("target_id") or intent.get("target")),
            "mood": _clean(intent.get("mood")),
            "style": _clean(intent.get("style")),
            "reasoning": _clean(intent.get("reasoning")),
        },
        "chosen_action": {
            "action": _clean(chosen.get("action")),
            "target": _clean(_dict(chosen.get("kwargs")).get("target") or chosen.get("target")),
            "say": _clean(chosen.get("say")),
        },
        "plan_steps": [_compact_step(step) for step in plan_steps if isinstance(step, dict)],
        "place": _place_digest(raw, graph, result, memory_payload),
        "mood": _numeric_dict(raw.get("mood")),
        "health": _numeric_dict(raw.get("health")),
        "social": _social_turn_digest(social_context, dialogue, creature_id),
        "execution": _execution_digest(previous_result, _dict(result.get("action_result"))),
        "reasoning": _clean(graph.get("reasoning") or result.get("reasoning") or memory_payload.get("reasoning")),
    }


def _memory_payload(graph: dict[str, Any]) -> dict[str, Any]:
    write = _dict(graph.get("memory_write"))
    raw_event = _dict(write.get("raw_event"))
    return _dict(raw_event.get("payload"))


def _compact_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": _clean(step.get("action")),
        "target": _clean(step.get("target")),
        "say": _clean(step.get("say")),
        "reason": _clean(step.get("reason")),
    }


def _place_digest(
    raw: dict[str, Any],
    graph: dict[str, Any],
    result: dict[str, Any],
    memory_payload: dict[str, Any],
) -> dict[str, Any]:
    raw_place = _dict(raw.get("place_context")) or _dict(memory_payload.get("place_context"))
    raw_spatial = _dict(raw.get("spatial_context")) or _dict(memory_payload.get("spatial_context"))
    graph_place = _dict(graph.get("place_memory_context")) or _dict(result.get("place_memory"))
    self_view = _dict(raw.get("self")) or _dict(memory_payload.get("self"))
    zones = _list(raw_spatial.get("zones"))
    zone_ids = [
        zone_id
        for zone in zones
        if isinstance(zone, dict)
        and (zone_id := _clean(zone.get("id")))
    ]
    current = (
        _clean(raw_place.get("current_zone_id"))
        or _clean(graph_place.get("current_zone_id"))
        or (zone_ids[-1] if zone_ids else "")
    )
    return {
        "current_zone_id": current,
        "active_zone_ids": _string_list(raw_place.get("active_zone_ids")) or zone_ids,
        "reachable_zone_ids": _string_list(raw_place.get("reachable_zone_ids")),
        "best_exploration_target": _clean(graph_place.get("best_exploration_target")),
        "location": self_view.get("location"),
        "current_action": _clean(self_view.get("current_action")),
    }


def _social_turn_digest(
    social_context: dict[str, Any],
    dialogue: list[Any],
    creature_id: str,
) -> dict[str, Any]:
    room = _dict(social_context.get("room"))
    decision = _dict(social_context.get("decision"))
    utterance = _dict(decision.get("utterance"))
    delivered = [_dict(item) for item in _list(social_context.get("delivered_inbox"))]
    relationships = [_dict(item) for item in _list(social_context.get("relationships"))]
    members = _string_list(room.get("members"))
    peers = [member for member in members if member != creature_id]

    heard = [
        {
            "from": _clean(item.get("from")),
            "text": _clean(item.get("text")),
            "tone": _clean(item.get("tone")),
            "target": _clean(item.get("target")),
        }
        for item in delivered
        if _clean(item.get("text"))
    ]
    said = {
        "text": _clean(utterance.get("text")),
        "tone": _clean(utterance.get("tone")),
        "target": _clean(utterance.get("target")),
    } if decision.get("spoke") and utterance else None

    return {
        "room_key": _clean(room.get("room_key")),
        "zone_id": _clean(room.get("zone_id")),
        "members": members,
        "peers": peers,
        "turn_count": _int(room.get("turn_count")),
        "decision_note": _clean(decision.get("note")),
        "spoke": bool(decision.get("spoke")),
        "said": said,
        "heard": heard,
        "relationship_deltas": _list(decision.get("relationship_deltas")),
        "relationships": relationships,
        "dialogue": [
            {
                "from": _clean(_dict(line).get("from")),
                "text": _clean(_dict(line).get("text")),
                "tone": _clean(_dict(line).get("tone")),
                "target": _clean(_dict(line).get("target")),
            }
            for line in dialogue
            if isinstance(line, dict) and _clean(line.get("text"))
        ],
    }


def _execution_digest(previous_result: dict[str, Any], action_result: dict[str, Any]) -> dict[str, Any]:
    previous_steps = [_dict(step) for step in _list(previous_result.get("steps"))]
    return {
        "previous_status": _clean(previous_result.get("status")),
        "previous_action": _clean(previous_result.get("action")),
        "previous_target": _clean(previous_result.get("target")),
        "previous_step_count": len(previous_steps),
        "previous_steps": [
            {
                "action": _clean(step.get("action")),
                "target": _clean(step.get("target")),
                "status": _clean(step.get("status")),
                "reason": _clean(step.get("reason")),
            }
            for step in previous_steps[-8:]
        ],
        "backend_status": _clean(action_result.get("status")),
        "backend_action": _clean(action_result.get("action")),
        "backend_target": _clean(action_result.get("target")),
    }


def _social_digest(turns: list[dict[str, Any]], creature_id: str) -> dict[str, Any]:
    rooms = Counter()
    peer_state: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "peer_id": "",
            "shared_room_turns": 0,
            "spoken_to": 0,
            "heard_from": 0,
            "trust": None,
            "affinity": None,
            "encounters": 0,
            "key_lines": [],
        }
    )
    spoken_turns = 0
    heard_turns = 0
    dialogue_count = 0

    for turn in turns:
        social = turn["social"]
        if social["room_key"]:
            rooms[social["room_key"]] += 1
        for peer in social["peers"]:
            state = peer_state[peer]
            state["peer_id"] = peer
            state["shared_room_turns"] += 1

        said = social.get("said")
        if said:
            spoken_turns += 1
            targets = [said["target"]] if said.get("target") else social["peers"]
            for peer in targets:
                if not peer:
                    continue
                state = peer_state[peer]
                state["peer_id"] = peer
                state["spoken_to"] += 1
                _append_line(state["key_lines"], turn["tick"], creature_id, said["text"])

        heard = social.get("heard") or []
        if heard:
            heard_turns += 1
        for item in heard:
            peer = _clean(item.get("from"))
            if not peer:
                continue
            state = peer_state[peer]
            state["peer_id"] = peer
            state["heard_from"] += 1
            _append_line(state["key_lines"], turn["tick"], peer, item.get("text"))

        for item in social.get("dialogue") or []:
            if _clean(item.get("text")):
                dialogue_count += 1

        for rel in social.get("relationships") or []:
            pair = _string_list(_dict(rel).get("pair"))
            if creature_id not in pair:
                continue
            peer = next((item for item in pair if item != creature_id), "")
            if not peer:
                continue
            state = peer_state[peer]
            state["peer_id"] = peer
            state["trust"] = _number_or_none(rel.get("trust"))
            state["affinity"] = _number_or_none(rel.get("affinity"))
            state["encounters"] = max(state["encounters"], _int(rel.get("encounters")))

    relationships = sorted(
        peer_state.values(),
        key=lambda item: (
            item["shared_room_turns"] + item["spoken_to"] + item["heard_from"],
            item["peer_id"],
        ),
        reverse=True,
    )
    return {
        "shared_room_turns": sum(1 for turn in turns if turn["social"]["room_key"]),
        "spoken_turns": spoken_turns,
        "heard_turns": heard_turns,
        "dialogue_count": dialogue_count,
        "rooms": _counter_items(rooms, sum(rooms.values())),
        "relationships": relationships,
    }


def _total_statistics(
    *,
    turns: list[dict[str, Any]],
    intent_counts: Counter[str],
    chosen_action_counts: Counter[str],
    plan_action_counts: Counter[str],
    target_counts: Counter[str],
    place_counts: Counter[str],
    previous_status_counts: Counter[str],
    social: dict[str, Any],
) -> dict[str, Any]:
    total_turns = len(turns)
    plan_step_total = sum(len(turn["plan_steps"]) for turn in turns)
    social_turns = _int(social.get("shared_room_turns"))
    spoken_turns = _int(social.get("spoken_turns"))
    heard_turns = _int(social.get("heard_turns"))
    relationships = _list(social.get("relationships"))

    drive_counts = Counter()
    for intent, count in intent_counts.items():
        drive_counts[_drive_bucket(intent)] += count

    action_counts = Counter()
    for action, count in plan_action_counts.items():
        action_counts[_action_bucket(action)] += count

    place_sequence = [
        turn["place"]["current_zone_id"]
        for turn in turns
        if turn["place"]["current_zone_id"]
    ]
    path_changes = sum(
        1
        for previous, current in zip(place_sequence, place_sequence[1:])
        if previous != current
    )
    execution_clean = sum(
        count
        for status, count in previous_status_counts.items()
        if status in {"done", "completed", "success", "succeeded"}
    )

    top_peer = _top_peer(relationships)
    stats = {
        "turns": {
            "total": total_turns,
            "with_plan": sum(1 for turn in turns if turn["plan_steps"]),
            "average_plan_length": round(plan_step_total / total_turns, 2)
            if total_turns
            else 0.0,
            "plan_step_total": plan_step_total,
        },
        "mainly": {
            "does": _top_counter_item(plan_action_counts),
            "chooses": _top_counter_item(chosen_action_counts),
            "wants": _top_counter_item(intent_counts),
            "goes": _top_counter_item(place_counts),
            "targets": _top_counter_item(target_counts),
            "socializes_with": top_peer,
        },
        "drive_balance": _counter_items(drive_counts, total_turns),
        "action_balance": _counter_items(action_counts, plan_step_total),
        "place_behavior": {
            "unique_places": len(place_counts),
            "path_changes": path_changes,
            "home_zone": _top_counter_item(place_counts),
            "roaming_ratio": _ratio(path_changes, max(1, len(place_sequence) - 1)),
        },
        "social_behavior": {
            "shared_room_turns": social_turns,
            "spoken_turns": spoken_turns,
            "heard_turns": heard_turns,
            "relationship_count": len(relationships),
            "social_turn_ratio": _ratio(social_turns, total_turns),
            "speech_ratio": _ratio(spoken_turns, total_turns),
            "listening_ratio": _ratio(heard_turns, total_turns),
            "top_peer": top_peer,
            "style_label": _social_stat_label(social_turns, spoken_turns, heard_turns, total_turns),
        },
        "execution_behavior": {
            "clean_completion_ratio": _ratio(execution_clean, sum(previous_status_counts.values())),
            "status_mix": _counter_items(previous_status_counts, sum(previous_status_counts.values())),
        },
    }
    stats["badges"] = _stat_badges(stats, intent_counts, action_counts, place_counts)
    return stats


def _drive_bucket(intent: str) -> str:
    intent = _clean(intent).upper()
    if intent in {"EXPLORE", "INVESTIGATE"}:
        return "curiosity"
    if intent == "SOCIALIZE":
        return "social"
    if intent in {"SEEK_FOOD", "SAFETY"}:
        return "needs_and_safety"
    if intent in {"REST", "IDLE"}:
        return "comfort"
    if intent == "SEEK_PLAYER":
        return "attachment"
    return "other"


def _action_bucket(action: str) -> str:
    action = _clean(action).lower()
    if action in {"go_to", "follow", "wander", "flee", "stop_moving"}:
        return "movement"
    if action in {"smell", "look_around", "alert", "face_sun"}:
        return "sensing"
    if action in {"vocalize", "nod_head"}:
        return "social_expression"
    if action in {"eat", "drink", "groom", "scratch"}:
        return "body_care"
    if action in {"sit", "lie", "sleep", "idle"}:
        return "resting"
    return "other"


def _top_peer(relationships: list[Any]) -> dict[str, Any] | None:
    if not relationships:
        return None
    peers = [_dict(item) for item in relationships]
    peers.sort(
        key=lambda item: (
            _int(item.get("shared_room_turns"))
            + _int(item.get("spoken_to"))
            + _int(item.get("heard_from")),
            _clean(item.get("peer_id")),
        ),
        reverse=True,
    )
    peer = peers[0]
    if not _clean(peer.get("peer_id")):
        return None
    return {
        "peer_id": _clean(peer.get("peer_id")),
        "shared_room_turns": _int(peer.get("shared_room_turns")),
        "spoken_to": _int(peer.get("spoken_to")),
        "heard_from": _int(peer.get("heard_from")),
        "trust": peer.get("trust"),
        "affinity": peer.get("affinity"),
    }


def _top_counter_item(counter: Counter[str]) -> dict[str, Any] | None:
    for name, count in counter.most_common(1):
        if name:
            return {"name": name, "count": count}
    return None


def _social_stat_label(
    social_turns: int,
    spoken_turns: int,
    heard_turns: int,
    total_turns: int,
) -> str:
    social_ratio = _ratio(social_turns, total_turns)
    if social_ratio == 0:
        return "solitary"
    if spoken_turns > heard_turns * 1.5:
        return "initiator"
    if heard_turns > spoken_turns * 1.5:
        return "listener"
    if social_ratio >= 0.5:
        return "social regular"
    return "occasional social"


def _stat_badges(
    stats: dict[str, Any],
    intent_counts: Counter[str],
    action_counts: Counter[str],
    place_counts: Counter[str],
) -> list[str]:
    badges: list[str] = []
    mainly = _dict(stats.get("mainly"))
    social = _dict(stats.get("social_behavior"))
    place = _dict(stats.get("place_behavior"))
    turns = _dict(stats.get("turns"))

    if top := _dict(mainly.get("wants")).get("name"):
        badges.append(f"main want: {top}")
    if top := _dict(mainly.get("does")).get("name"):
        badges.append(f"signature action: {top}")
    if top := _dict(mainly.get("goes")).get("name"):
        badges.append(f"home zone: {top}")
    if peer := _dict(mainly.get("socializes_with")).get("peer_id"):
        badges.append(f"closest peer in logs: {peer}")
    badges.append(f"social style: {social.get('style_label', 'unknown')}")

    if _int(place.get("path_changes")) >= max(2, _int(turns.get("total")) // 3):
        badges.append("roaming pattern")
    if intent_counts.get("EXPLORE", 0) or intent_counts.get("INVESTIGATE", 0):
        badges.append("curiosity-led")
    if action_counts.get("sensing", 0) >= action_counts.get("movement", 0):
        badges.append("senses before moving")
    if place_counts and len(place_counts) == 1:
        badges.append("territorially steady")
    return badges[:8]


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def _memorable_turns(turns: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, dict[str, Any]]] = []
    previous_intent = ""
    for index, turn in enumerate(turns):
        score = 0
        intent = turn["intent"]["name"]
        social = turn["social"]
        execution = turn["execution"]
        mood = turn["mood"]
        if social["spoke"]:
            score += 5
        if social["heard"]:
            score += 4
        if execution["previous_status"] and execution["previous_status"] not in {
            "done",
            "completed",
            "success",
            "succeeded",
        }:
            score += 4
        if intent and previous_intent and intent != previous_intent:
            score += 2
        if intent in {"SOCIALIZE", "SAFETY", "SEEK_FOOD", "REST"}:
            score += 2
        if mood.get("fear", 0.0) >= 0.55 or mood.get("curiosity", 0.0) >= 0.75:
            score += 2
        if turn["place"]["best_exploration_target"]:
            score += 1
        if score:
            scored.append((score, -index, _episode_source(turn)))
        previous_intent = intent

    scored.sort(reverse=True)
    return [turn for _score, _index, turn in scored[:limit]]


def _episode_source(turn: dict[str, Any]) -> dict[str, Any]:
    social = turn["social"]
    said = social.get("said") or {}
    heard = social.get("heard") or []
    return {
        "tick": turn["tick"],
        "request_id": turn["request_id"],
        "intent": turn["intent"],
        "place": turn["place"]["current_zone_id"],
        "chosen_action": turn["chosen_action"],
        "plan": turn["plan_steps"][:5],
        "social": {
            "room_key": social["room_key"],
            "peers": social["peers"],
            "said": said,
            "heard": heard[:3],
        },
        "execution": turn["execution"],
        "reasoning": turn["reasoning"],
    }


def _sample_turns(
    turns: list[dict[str, Any]],
    memorable: list[dict[str, Any]],
    *,
    edge: int = 8,
    limit: int = 32,
) -> list[dict[str, Any]]:
    if len(turns) <= limit:
        return [_sample_turn(turn) for turn in turns]

    keep_ticks = {turn["tick"] for turn in memorable[:12]}
    samples = turns[:edge] + [turn for turn in turns if turn["tick"] in keep_ticks] + turns[-edge:]
    deduped: dict[int, dict[str, Any]] = {}
    for turn in samples:
        deduped[turn["tick"]] = _sample_turn(turn)
    return [deduped[key] for key in sorted(deduped)]


def _sample_turn(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "tick": turn["tick"],
        "intent": turn["intent"]["name"],
        "action": turn["chosen_action"]["action"],
        "target": turn["chosen_action"]["target"],
        "place": turn["place"]["current_zone_id"],
        "said": _dict(turn["social"].get("said")).get("text", ""),
        "heard_count": len(turn["social"].get("heard") or []),
        "previous_status": turn["execution"]["previous_status"],
    }


def _episode_card(turn: dict[str, Any]) -> dict[str, Any]:
    intent = _dict(turn.get("intent"))
    action = _dict(turn.get("chosen_action"))
    social = _dict(turn.get("social"))
    place = _clean(turn.get("place")) or "an unknown place"
    said = _dict(social.get("said"))
    heard = _list(social.get("heard"))
    title_bits = [_clean(intent.get("name")) or "IDLE"]
    if action.get("action"):
        title_bits.append(_clean(action.get("action")))
    return {
        "tick": turn.get("tick"),
        "title": " -> ".join(title_bits),
        "scene": _episode_scene(place, said, heard),
        "intent": intent,
        "plan": turn.get("plan", []),
        "why_it_matters": _clean(turn.get("reasoning")) or "This turn stood out in the backend decision trace.",
    }


def _relationship_card(peer: dict[str, Any]) -> dict[str, Any]:
    peer_id = _clean(peer.get("peer_id")) or "unknown"
    spoken = _int(peer.get("spoken_to"))
    heard = _int(peer.get("heard_from"))
    shared = _int(peer.get("shared_room_turns"))
    trust = peer.get("trust")
    affinity = peer.get("affinity")
    parts = [f"shared {shared} room turn(s)"]
    if spoken:
        parts.append(f"spoke {spoken} time(s)")
    if heard:
        parts.append(f"heard {heard} time(s)")
    if trust is not None or affinity is not None:
        parts.append(f"bond trust={trust}, affinity={affinity}")
    return {
        "peer_id": peer_id,
        "summary": "; ".join(parts),
        "spoken_to": spoken,
        "heard_from": heard,
        "shared_room_turns": shared,
        "trust": trust,
        "affinity": affinity,
        "key_lines": peer.get("key_lines", [])[:5],
    }


def _arcs(digest: dict[str, Any]) -> list[dict[str, Any]]:
    mix = _dict(digest.get("mix"))
    places = _dict(digest.get("places"))
    social = _dict(digest.get("social"))
    execution = _dict(digest.get("execution"))
    mood = _dict(digest.get("mood"))
    return [
        {
            "label": "Decision Weather",
            "detail": _mix_sentence("intent", _list(mix.get("intents"))),
        },
        {
            "label": "Body Language",
            "detail": _mood_sentence(mood),
        },
        {
            "label": "Territory",
            "detail": _place_sentence(places),
        },
        {
            "label": "Social Gravity",
            "detail": _social_style(social),
        },
        {
            "label": "Follow-through",
            "detail": _execution_sentence(execution),
        },
    ]


def _open_threads(digest: dict[str, Any]) -> list[str]:
    threads: list[str] = []
    execution = _dict(digest.get("execution"))
    problem_turns = _list(execution.get("problem_turns"))
    targets = _list(_dict(digest.get("mix")).get("targets"))
    places = _dict(digest.get("places"))
    social = _dict(digest.get("social"))

    if problem_turns:
        threads.append(
            f"{len(problem_turns)} turn(s) had non-clean Unity completion feedback; check whether the next plan adapted."
        )
    if targets:
        threads.append(f"Repeated attention to {targets[0]['name']} could become a recurring object/place motif.")
    if _list(places.get("sequence")):
        last_place = _list(places.get("sequence"))[-1]
        if isinstance(last_place, dict) and last_place.get("name"):
            threads.append(f"The latest known place is {last_place['name']}; next processing pass can ask what changed there.")
    if not _list(social.get("relationships")):
        threads.append("No durable peer relationship appeared yet; solitude is still part of this cat's record.")
    return threads[:6]


def _subtitle(source: dict[str, Any], top_intents: list[Any], social: dict[str, Any]) -> str:
    tick_range = _dict(source.get("tick_range"))
    first, last = tick_range.get("first"), tick_range.get("last")
    top = _clean(_dict(top_intents[0]).get("name")) if top_intents else "IDLE"
    return (
        f"{source.get('turn_count', 0)} backend turn(s), ticks {first} to {last}; "
        f"main weather: {top}; social room turns: {social.get('shared_room_turns', 0)}."
    )


def _one_line(display: str, digest: dict[str, Any]) -> str:
    intents = _list(_dict(digest.get("mix")).get("intents"))
    actions = _list(_dict(digest.get("mix")).get("plan_actions"))
    top_intent = _clean(_dict(intents[0]).get("name")) if intents else "IDLE"
    top_action = _clean(_dict(actions[0]).get("name")) if actions else "idle"
    tags = _temperament_tags(digest)
    flavor = ", ".join(tags[:2]) if tags else "watchful"
    return f"{display} reads as a {flavor} cat whose decisions often turn {top_intent} into {top_action}."


def _temperament_tags(digest: dict[str, Any]) -> list[str]:
    averages = _dict(_dict(digest.get("mood")).get("averages"))
    intents = {item["name"]: item["count"] for item in _list(_dict(digest.get("mix")).get("intents")) if isinstance(item, dict)}
    tags: list[str] = []
    if averages.get("curiosity", 0) >= 0.55 or intents.get("EXPLORE", 0):
        tags.append("curious")
    if averages.get("fear", 0) >= 0.35 or intents.get("SAFETY", 0):
        tags.append("cautious")
    if averages.get("social", 0) >= 0.35 or intents.get("SOCIALIZE", 0):
        tags.append("socially aware")
    if averages.get("energy", 0) >= 0.65:
        tags.append("high-energy")
    if intents.get("REST", 0):
        tags.append("self-regulating")
    if intents.get("SEEK_FOOD", 0):
        tags.append("need-led")
    return tags or ["watchful"]


def _social_style(social: dict[str, Any]) -> str:
    shared = _int(social.get("shared_room_turns"))
    spoken = _int(social.get("spoken_turns"))
    heard = _int(social.get("heard_turns"))
    if not shared:
        return "Mostly solitary in this slice; no shared social room became part of the record."
    if spoken and heard:
        return f"Reciprocal but light: {shared} shared room turn(s), {spoken} speaking turn(s), and {heard} listening turn(s)."
    if spoken:
        return f"Initiates contact gently: {spoken} speaking turn(s) across {shared} shared room turn(s)."
    if heard:
        return f"Listener first: heard peers on {heard} turn(s) across {shared} shared room turn(s)."
    return f"Co-present without much talk: {shared} shared room turn(s) and little dialogue."


def _solitude_style(digest: dict[str, Any]) -> str:
    intents = {item["name"]: item["count"] for item in _list(_dict(digest.get("mix")).get("intents")) if isinstance(item, dict)}
    if intents.get("EXPLORE", 0) or intents.get("INVESTIGATE", 0):
        return "Uses alone-time to inspect places and cues rather than simply idle."
    if intents.get("REST", 0):
        return "Uses alone-time to downshift and recover."
    return "Solitude currently reads as quiet watchfulness."


def _mix_sentence(kind: str, items: list[Any]) -> str:
    if not items:
        return f"No {kind} mix is available yet."
    top = [_dict(item) for item in items[:3]]
    return "Top " + kind + "s: " + ", ".join(
        f"{item.get('name')} ({item.get('count')})" for item in top
    ) + "."


def _mood_sentence(mood: dict[str, Any]) -> str:
    averages = _dict(mood.get("averages"))
    if not averages:
        return "Mood readings were not present in these records."
    top = sorted(averages.items(), key=lambda item: item[1], reverse=True)[:3]
    return "Strongest average mood signals: " + ", ".join(
        f"{name} {round(value, 2)}" for name, value in top
    ) + "."


def _place_sentence(places: dict[str, Any]) -> str:
    visited = _list(places.get("visited"))
    sequence = _list(places.get("sequence"))
    if not visited:
        return "No stable place signal appeared in these records."
    detail = _mix_sentence("place", visited)
    if sequence:
        detail += f" The path changed {max(0, len(sequence) - 1)} time(s)."
    return detail


def _execution_sentence(execution: dict[str, Any]) -> str:
    statuses = _list(execution.get("previous_statuses"))
    if not statuses:
        return "No Unity completion reports were available yet."
    return _mix_sentence("completion status", statuses)


def _episode_scene(place: str, said: dict[str, Any], heard: list[Any]) -> str:
    if said and said.get("text"):
        target = f" toward {said.get('target')}" if said.get("target") else ""
        return f"At {place}, the cat said{target}: {said.get('text')}"
    if heard:
        line = _dict(heard[0])
        return f"At {place}, the cat heard {line.get('from')}: {line.get('text')}"
    return f"At {place}, the decision trace marked a turn worth remembering."


def _numeric_series_digest(values: list[dict[str, float]]) -> dict[str, Any]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for item in values:
        for key, value in item.items():
            buckets[key].append(value)
    averages = {
        key: round(sum(nums) / len(nums), 3)
        for key, nums in sorted(buckets.items())
        if nums
    }
    first = {key: nums[0] for key, nums in sorted(buckets.items()) if nums}
    last = {key: nums[-1] for key, nums in sorted(buckets.items()) if nums}
    return {
        "averages": averages,
        "first": first,
        "last": last,
        "deltas": {
            key: round(last[key] - first[key], 3)
            for key in first.keys() & last.keys()
        },
    }


def _compressed_sequence(values: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for value in values:
        name = _clean(value)
        if not name:
            continue
        if out and out[-1]["name"] == name:
            out[-1]["turns"] += 1
        else:
            out.append({"name": name, "turns": 1})
    return out


def _counter_items(counter: Counter[str], total: int, limit: int = 12) -> list[dict[str, Any]]:
    out = []
    for name, count in counter.most_common(limit):
        if not name:
            continue
        item: dict[str, Any] = {"name": name, "count": count}
        if total:
            item["share"] = round(count / total, 3)
        out.append(item)
    return out


def _append_line(lines: list[dict[str, Any]], tick: int, speaker: str, text: Any) -> None:
    clean = _clean(text)
    if clean and len(lines) < 8:
        lines.append({"tick": tick, "from": speaker, "text": clean})


def _coerce_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
        return [data]
    return []


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL in {path}:{line_no}: {exc}") from exc
        if isinstance(item, dict):
            records.append(item)
    return records


def _first_text(items: list[dict[str, Any]], key: str) -> str:
    for item in items:
        text = _clean(item.get(key))
        if text:
            return text
    return ""


def _last_text(items: list[dict[str, Any]], key: str) -> str:
    for item in reversed(items):
        text = _clean(item.get(key))
        if text:
            return text
    return ""


def _numeric_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(item)
        for key, item in value.items()
        if isinstance(item, (int, float))
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = _clean(value)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _clean(item))]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _display_name(creature_id: str) -> str:
    text = creature_id.replace("cat_", "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Unknown Cat"


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def _number_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


__all__ = [
    "DEFAULT_JOURNAL_DIR",
    "PROCESSED_JOURNAL_FILENAME",
    "build_processed_journal",
    "load_cat_records",
    "load_records",
    "preprocess_cat_journal",
    "processed_path_for",
    "write_processed_journal",
]
