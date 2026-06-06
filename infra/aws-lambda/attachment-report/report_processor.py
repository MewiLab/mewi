"""Pure raw-session -> processed-report derivation for attachment-report Lambda.

Lambda owns the deterministic website-ready report shape. FastAPI intentionally
has no copy of this processor; it only stores raw sessions and enqueues jobs.

This module is intentionally pure: no filesystem, no env, no CLI. All I/O
(loading raw sessions, loading user_info, writing processed output) lives in the
Lambda handler and ``_s3io.py``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ── cat meta (persona-driven) ─────────────────────────────────────────────────
CAT_META: dict[str, dict] = {
    "mewi": {
        "name": "Mewi",
        "accent": "#888780",
        "archetype": "ISFJ · observant, careful, loyal to familiar places",
        "trait": "Smell-led. Reads a place before her body moves. Affection arrives slowly and lasts.",
    },
    "miso": {
        "name": "Miso",
        "accent": "#639922",
        "archetype": "ISFP · gentle, present, sensory, slow-moving",
        "trait": "Strongly food-motivated. Affectionate with familiar humans. Conservative about effort.",
    },
    "yuzu": {
        "name": "Yuzu",
        "accent": "#BA7517",
        "archetype": "ENTP · restless, provocative, tests others",
        "trait": "Drawn to motion and reaction. Abandons one plan the moment a more interesting one appears.",
    },
    "haru": {
        "name": "Haru",
        "accent": "#534AB7",
        "archetype": "INFJ · quiet, intuitive, attuned to others",
        "trait": "Quietly devoted to one or two beings. Presence over interaction. Slow to enter, slow to leave.",
    },
}

# ── action categories for radar ──────────────────────────────────────────────
RADAR_ACTIONS: dict[str, list[str]] = {
    "Approach":     ["approach"],
    "Retreat":      ["retreat", "flee", "stop_moving"],
    "Offer item":   ["offer_item"],
    "Wait / dwell": ["sit", "wait", "crouch"],
    "Call out":     ["call_out", "vocalize"],
    "Pet attempt":  ["pet_attempt"],
}

# Unity is the authority for the player-cat action vocabulary. Keep this table
# in lockstep with PlayerCatSocialInputRouter.BuildDefaultBindings().
PLAYER_CAT_ACTION_SCHEMA: dict[str, dict[str, str]] = {
    "player_play_invite": {"motor_action": "scratch", "family": "affiliative_bid"},
    "player_meow": {"motor_action": "vocalize", "family": "affiliative_bid"},
    "player_nod_yes": {"motor_action": "nod_head", "family": "affiliative_bid"},
    "player_shake_no": {"motor_action": "no", "family": "boundary_refusal"},
    "player_sit_near": {"motor_action": "sit", "family": "calm_presence"},
    "player_groom": {"motor_action": "groom", "family": "affiliative_bid"},
    "player_poop": {"motor_action": "poop", "family": "exploration_resource"},
    "player_pee": {"motor_action": "pee", "family": "exploration_resource"},
    "player_scratch": {"motor_action": "scratch", "family": "exploration_resource"},
    "player_lie": {"motor_action": "lie", "family": "calm_presence"},
    "player_sleep": {"motor_action": "sleep", "family": "calm_presence"},
    "player_smell": {"motor_action": "smell", "family": "cautious_investigation"},
    "player_look_around": {"motor_action": "look_around", "family": "cautious_investigation"},
    "player_alert": {"motor_action": "alert", "family": "boundary_refusal"},
    "player_push": {"motor_action": "push", "family": "intrusion_threat"},
    "player_shake": {"motor_action": "shake", "family": "fear_startle_shutdown"},
    "player_dig": {"motor_action": "dig", "family": "exploration_resource"},
    "player_crawl": {"motor_action": "crawl", "family": "cautious_investigation"},
    "player_drink": {"motor_action": "drink", "family": "exploration_resource"},
    "player_flinch": {"motor_action": "flinch", "family": "fear_startle_shutdown"},
    "player_startle": {"motor_action": "startle", "family": "fear_startle_shutdown"},
    "player_stun": {"motor_action": "stun", "family": "fear_startle_shutdown"},
    "player_open_chest": {"motor_action": "open_chest", "family": "exploration_resource"},
    "player_eat": {"motor_action": "eat", "family": "exploration_resource"},
    "player_attack": {"motor_action": "", "family": "intrusion_threat"},
}

PLAYER_ACTION_FAMILIES = (
    "affiliative_bid",
    "calm_presence",
    "cautious_investigation",
    "exploration_resource",
    "boundary_refusal",
    "intrusion_threat",
    "fear_startle_shutdown",
    "unknown",
)

CAT_NARRATIVE: dict[str, dict[str, str]] = {
    "mewi": {
        "absent": "Mewi stayed outside the readable edge of the session.",
        "positive": "Mewi let the distance shrink and kept watching without leaving.",
        "food": "Mewi accepted food after you gave her space.",
        "calm": "Mewi settled after your movement slowed.",
        "caution": "Mewi stayed cautious and kept checking the threshold.",
        "dip": "Mewi's trust dipped; sudden motion still matters to her.",
        "flat": "Mewi recorded your presence, but did not move the bond much.",
    },
    "miso": {
        "absent": "Miso did not enter the main interaction loop.",
        "positive": "Miso moved closer in the practical, food-led way she trusts.",
        "food": "Miso responded to the offer and made the session warmer.",
        "calm": "Miso stayed near the quiet part of your presence.",
        "caution": "Miso watched first and spent little energy.",
        "dip": "Miso lost a little confidence without enough reinforcement.",
        "flat": "Miso remained steady, with no strong new signal.",
    },
    "yuzu": {
        "absent": "Yuzu did not give you a clean read this session.",
        "positive": "Yuzu noticed your reaction pattern and kept testing it.",
        "food": "Yuzu registered the offer, but novelty still mattered more.",
        "calm": "Yuzu watched what happened when you did not chase the reaction.",
        "caution": "Yuzu stayed restless and hard to pin down.",
        "dip": "Yuzu's interest fell; the interaction became too predictable.",
        "flat": "Yuzu stayed volatile and gave no lasting trust gain.",
    },
    "haru": {
        "absent": "Haru stayed outside the visible field, still reading the room.",
        "positive": "Haru allowed quiet presence to become part of the session.",
        "food": "Haru noticed the offer, but presence mattered more than the item.",
        "calm": "Haru stayed because the room felt calmer.",
        "caution": "Haru held distance and watched the emotional weather.",
        "dip": "Haru withdrew; she noticed the shift before anyone named it.",
        "flat": "Haru held her distance without changing the bond.",
    },
}

ACTION_COPY = {
    "approach": "approached",
    "stop_moving": "stopped moving",
    "offer_item": "offered food",
    "sit": "sat still",
    "wait": "waited",
    "crouch": "crouched",
    "retreat": "stepped back",
    "call_out": "called out",
    "pet_attempt": "tried to pet",
}

CAT_ACTION_COPY = {
    "alert": "became alert",
    "sit": "sat down",
    "eat": "ate",
    "approach": "approached",
    "groom": "groomed",
    "vocalize": "vocalized",
    "flee": "left",
    "bat": "batted once",
    "nod_head": "softened her posture",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _session_trust(events: list[dict], cat_id: str) -> int:
    """Return the final trust value for a cat in a session's event list."""
    val = 0
    for ev in events:
        if ev.get("actor") == "cat" and ev.get("cat_id") == cat_id:
            val = ev.get("trust_after", val)
    return val


def _reaction_latencies(events: list[dict]) -> list[float]:
    """For each human action, find the time until the next cat event."""
    latencies: list[float] = []
    human_t: float | None = None
    for ev in events:
        if ev["actor"] == "human":
            human_t = ev["t"]
        elif ev["actor"] == "cat" and human_t is not None:
            latencies.append(round(ev["t"] - human_t, 2))
            human_t = None
    return latencies


def _human_action_counts(sessions: list[dict]) -> dict[str, int]:
    """Count human actions across all sessions for radar chart."""
    counts: dict[str, int] = defaultdict(int)
    for sess in sessions:
        for ev in sess["events"]:
            if ev["actor"] == "human":
                counts[ev["action"]] += 1
    return dict(counts)


def _radar_values(action_counts: dict[str, int]) -> dict[str, int]:
    """Map raw action counts to radar axes as percentages (0–100)."""
    totals = {axis: 0 for axis in RADAR_ACTIONS}
    grand = 0
    for action, count in action_counts.items():
        for axis, keywords in RADAR_ACTIONS.items():
            if action in keywords:
                totals[axis] += count
                grand += count
    if grand == 0:
        return {axis: 0 for axis in RADAR_ACTIONS}
    return {axis: round(v / grand * 100) for axis, v in totals.items()}


def _attention_pct(sessions: list[dict]) -> dict[str, int]:
    """Estimate attention % per cat from proximity-event counts (sums to 100)."""
    counts: dict[str, int] = defaultdict(int)
    for sess in sessions:
        for ev in sess["events"]:
            if ev.get("actor") == "cat":
                counts[ev["cat_id"]] += 1
    total = sum(counts.values()) or 1
    raw = {k: v / total for k, v in counts.items()}
    out = {k: round(v * 100) for k, v in raw.items()}
    diff = 100 - sum(out.values())
    if out:
        largest = max(out, key=lambda k: out[k])
        out[largest] += diff
    return out


def _multi_cat_encounters(sessions: list[dict]) -> list[dict]:
    encounters: list[dict] = []
    for sess in sessions:
        for enc in sess.get("multi_cat_encounters", []):
            encounters.append({
                "situation": " + ".join(c.title() for c in enc["cats_present"]) + " both nearby",
                "choice": enc["human_action"].replace("_", " "),
                "freq": 1,
                "outcome": enc.get("outcome", "—").replace("_", " "),
            })
    merged: dict[str, dict] = {}
    for enc in encounters:
        key = enc["situation"] + enc["choice"]
        if key in merged:
            merged[key]["freq"] += 1
        else:
            merged[key] = dict(enc)
    result = list(merged.values())
    for r in result:
        r["freq"] = f'{r["freq"]}×'
    return result


def _attachment_profile(action_counts: dict[str, int], cat_trusts: dict[str, list[int]]) -> list[dict]:
    """Derive attachment profile dimensions from action counts and trust arcs."""
    total_actions = max(sum(action_counts.values()), 1)

    def pct(keys: list[str]) -> int:
        return round(sum(action_counts.get(k, 0) for k in keys) / total_actions * 100)

    patience = min(pct(["wait", "sit", "crouch", "stop_moving"]) * 2, 100)

    approach_n = action_counts.get("approach", 0)
    retreat_n = action_counts.get("retreat", 0) + action_counts.get("stop_moving", 0)
    oscillation = 100 - min(round(abs(approach_n - retreat_n) / max(approach_n + retreat_n, 1) * 100), 100)

    offer = min(pct(["offer_item"]) * 3, 100)
    dwell = min(pct(["sit", "wait", "crouch"]) * 2, 100)
    persistence = min(pct(["pet_attempt"]) * 2, 100)

    final_trusts = [trusts[-1] for trusts in cat_trusts.values() if trusts]
    if len(final_trusts) >= 2:
        avg = sum(final_trusts) / len(final_trusts)
        variance = sum((t - avg) ** 2 for t in final_trusts) / len(final_trusts)
        selectivity = min(round(variance / 5), 100)
    else:
        selectivity = 50

    return [
        {"label": "Patience under rejection",        "value": patience,     "color": "#639922"},
        {"label": "Low approach-retreat oscillation", "value": oscillation,  "color": "#639922"},
        {"label": "Offer without demanding return",   "value": offer,        "color": "#BA7517"},
        {"label": "Zone-dwell without action",        "value": dwell,        "color": "#639922"},
        {"label": "Persistence after avoidance",      "value": persistence,  "color": "#888780"},
        {"label": "Selectivity across cats",          "value": selectivity,  "color": "#639922"},
    ]


def _profile_value(profile: list[dict], label: str) -> int:
    for item in profile:
        if item["label"] == label:
            return int(item["value"])
    return 0


def _feature_value(features: list[dict], label: str) -> int:
    for item in features:
        if item.get("label") == label:
            return int(item.get("value") or 0)
    return 0


def _attachment_analysis_from_features(
    features: list[dict],
    interaction_signature: dict[str, Any],
    session_count: int,
) -> dict[str, Any]:
    soft = _feature_value(features, "Attuned soft bids")
    respect = _feature_value(features, "Respect for distance")
    repair = _feature_value(features, "Repair after rupture")
    pursuit = _feature_value(features, "Pursuit pressure")
    threat = _feature_value(features, "Threat / intrusion pressure")
    explore = _feature_value(features, "Exploration over reassurance")

    secure_score = _score((soft * 0.35) + (respect * 0.25) + (repair * 0.25) + ((100 - threat) * 0.15))
    anxious_score = _score((pursuit * 0.45) + (soft * 0.2) + ((100 - respect) * 0.2) + ((100 - repair) * 0.15))
    avoidant_score = _score((explore * 0.35) + (respect * 0.35) + ((100 - soft) * 0.2) + ((100 - pursuit) * 0.1))
    fearful_score = _score((threat * 0.35) + (pursuit * 0.25) + ((100 - repair) * 0.25) + ((100 - respect) * 0.15))

    action_counts = interaction_signature.get("action_counts") or {}
    total_actions = sum(int(value or 0) for value in action_counts.values())
    family_pct = interaction_signature.get("action_family_pct") or {}
    dominant_family = max(family_pct, key=lambda key: family_pct.get(key, 0), default="unknown")
    session_label = f"{session_count}-session" if session_count else "session"

    if total_actions <= 0:
        return {
            "type": "Insufficient player-cat evidence",
            "modifier": "no explicit player-cat actions",
            "confidence": "Low",
            "scores": {
                "secure": 0,
                "anxious": 0,
                "avoidant": 0,
                "fearful_avoidant": 0,
            },
            "summary": (
                "This report does not contain explicit player-cat actions, so the attachment "
                "leaning is intentionally left unassigned."
            ),
            "evidence": [
                {
                    "label": "Player-cat action base",
                    "detail": "0 explicit player-cat actions were counted.",
                },
                {
                    "label": "Attachment feature base",
                    "detail": "All attachment feature bars remain at 0 because there is no player-cat action stream to interpret.",
                },
            ],
            "caveat": f"This is a behavioral reading of a {session_label} game trace, not a clinical diagnosis.",
        }
    elif secure_score >= anxious_score and secure_score >= avoidant_score and secure_score >= fearful_score:
        attachment_type = "Secure-leaning attachment"
        modifier = "attuned bids with distance respect"
        confidence = "Moderate"
        summary = (
            "Your trace reads closest to secure attachment: player-cat actions combine available bids "
            "with enough distance respect for the cats to respond without pressure."
        )
    elif anxious_score >= avoidant_score and anxious_score >= fearful_score:
        attachment_type = "Anxious-preoccupied leaning"
        modifier = "heightened pursuit under uncertainty"
        confidence = "Moderate"
        summary = (
            "Your trace leans toward anxious-preoccupied attachment: uncertainty is more likely to "
            "pull the player-cat toward repeated bids or pursuit pressure."
        )
    elif avoidant_score >= fearful_score:
        attachment_type = "Dismissive-avoidant leaning"
        modifier = "self-protective distance"
        confidence = "Moderate"
        summary = (
            "Your trace leans toward dismissive-avoidant attachment: distance and exploration are "
            "stronger than direct bids for reassurance."
        )
    else:
        attachment_type = "Fearful-avoidant leaning"
        modifier = "mixed threat, pursuit, and caution"
        confidence = "Moderate"
        summary = (
            "Your trace leans toward fearful-avoidant attachment: caution, pressure, or threat signals "
            "compete with the wish to approach."
        )

    family_value = family_pct.get(dominant_family, 0)
    family_label = dominant_family.replace("_", " ")

    return {
        "type": attachment_type,
        "modifier": modifier,
        "confidence": confidence,
        "scores": {
            "secure": secure_score,
            "anxious": anxious_score,
            "avoidant": avoidant_score,
            "fearful_avoidant": fearful_score,
        },
        "summary": summary,
        "evidence": [
            {
                "label": "Player-cat action base",
                "detail": f"{total_actions} explicit player-cat actions were counted; the dominant family is {family_label} at {family_value}%.",
            },
            {
                "label": "Secure-base signal",
                "detail": f"Attuned soft bids are {soft}% and respect for distance is {respect}%, showing how contact bids balance with space.",
            },
            {
                "label": "Repair and pressure",
                "detail": f"Repair after rupture is {repair}%, pursuit pressure is {pursuit}%, and threat / intrusion pressure is {threat}%.",
            },
            {
                "label": "Exploration signal",
                "detail": f"Exploration over reassurance is {explore}%, capturing scanning, cautious investigation, and resource-directed actions.",
            },
        ],
        "caveat": f"This is a behavioral reading of a {session_label} game trace, not a clinical diagnosis.",
    }


def _attachment_analysis(profile: list[dict], cat_trusts: dict[str, list[int]]) -> dict[str, Any]:
    patience = _profile_value(profile, "Patience under rejection")
    oscillation = _profile_value(profile, "Low approach-retreat oscillation")
    offer = _profile_value(profile, "Offer without demanding return")
    dwell = _profile_value(profile, "Zone-dwell without action")
    persistence = _profile_value(profile, "Persistence after avoidance")
    selectivity = _profile_value(profile, "Selectivity across cats")

    secure_score = round((patience + oscillation + offer + dwell) / 4)
    anxious_score = round((persistence + (100 - oscillation) + (100 - patience)) / 3)
    avoidant_score = round(((100 - offer) + (100 - dwell) + selectivity) / 3)
    fearful_score = round(((100 - oscillation) + (100 - patience) + selectivity) / 3)

    if secure_score >= 60 and patience >= 60 and dwell >= 55 and persistence <= 45:
        attachment_type = "Secure-leaning attachment"
        modifier = "patient, selective attunement"
        summary = (
            "Your trace reads closest to secure attachment: you stayed available without crowding, "
            "offered contact without demanding return, and repaired after distance or setback."
        )
    elif anxious_score >= avoidant_score and anxious_score >= fearful_score:
        attachment_type = "Anxious-preoccupied leaning"
        modifier = "contact-seeking under uncertainty"
        summary = (
            "Your trace leans toward anxious-preoccupied attachment: uncertainty tends to pull you "
            "toward extra bids for contact, reassurance, or proximity."
        )
    elif avoidant_score >= fearful_score:
        attachment_type = "Dismissive-avoidant leaning"
        modifier = "self-protective distance"
        summary = (
            "Your trace leans toward dismissive-avoidant attachment: distance is preserved quickly, "
            "and bids for contact are limited when the cats do not respond."
        )
    else:
        attachment_type = "Fearful-avoidant leaning"
        modifier = "mixed approach and retreat"
        summary = (
            "Your trace leans toward fearful-avoidant attachment: closeness and caution alternate, "
            "especially after rejection or ambiguous signals."
        )

    trust_dips = sum(
        1
        for arc in cat_trusts.values()
        for i in range(1, len(arc))
        if arc[i] < arc[i - 1]
    )
    session_count = max((len(arc) for arc in cat_trusts.values()), default=0)
    session_label = f"{session_count}-session" if session_count else "session"
    final_session = f"session {session_count}" if session_count else "the final session"
    stable_cats = [
        CAT_META.get(cat_id, {}).get("name", cat_id)
        for cat_id, arc in cat_trusts.items()
        if arc and arc[-1] >= arc[0]
    ]
    stable_detail = ", ".join(stable_cats) if stable_cats else "the tracked cats"

    return {
        "type": attachment_type,
        "modifier": modifier,
        "confidence": "Moderate",
        "scores": {
            "secure": secure_score,
            "anxious": anxious_score,
            "avoidant": avoidant_score,
            "fearful_avoidant": fearful_score,
        },
        "summary": summary,
        "evidence": [
            {
                "label": "Secure-base signal",
                "detail": f"Patience under rejection is {patience}% and zone-dwell without action is {dwell}%, so the dominant pattern is staying present without forcing a response.",
            },
            {
                "label": "Low anxious pursuit",
                "detail": f"Persistence after avoidance is {persistence}%, which suggests you usually let distance exist instead of chasing reassurance.",
            },
            {
                "label": "Repair after rupture",
                "detail": f"The trust arcs include {trust_dips} dips across {session_count} sessions; by {final_session}, {stable_detail} finish stable or higher than they began.",
            },
            {
                "label": "Selective attunement",
                "detail": f"Selectivity is {selectivity}%: you formed a primary bond while still allowing different cats to keep different distances.",
            },
        ],
        "caveat": f"This is a behavioral reading of a {session_label} game trace, not a clinical diagnosis.",
    }


ATTACHMENT_MODE_DEFAULT = "default"
ATTACHMENT_MODE_RULE_ALIASES = {"default", "deterministic", "rule", "fallback"}


def _run_attachment_analysis(
    mode: str,
    profile: list[dict],
    cat_trusts: dict[str, list[int]],
    *,
    user_id: str,
    sessions: list[dict],
    attachment_features: list[dict] | None = None,
    interaction_signature: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic analysis.

    The Lambda handler owns Claude/RAG enrichment and may replace this nested
    block after the full deterministic page shape is built.
    """
    normalized_mode = (mode or ATTACHMENT_MODE_DEFAULT).strip().lower()
    if normalized_mode not in ATTACHMENT_MODE_RULE_ALIASES:
        logger.warning(
            "Unknown attachment_mode=%r for user_id=%s; using deterministic rule.",
            mode,
            user_id,
        )
    if attachment_features:
        return _attachment_analysis_from_features(
            attachment_features,
            interaction_signature or {},
            len(sessions),
        )
    return _attachment_analysis(profile, cat_trusts)


def _session_events_for_log(sessions: list[dict], cat_id: str = "mewi") -> list[dict]:
    """Extract a readable sequence log from the session with the most events."""
    best_sess = max(sessions, key=lambda s: sum(
        1 for e in s["events"] if e.get("cat_id") == cat_id
    ))
    rows = []
    for ev in best_sess["events"]:
        if ev["actor"] == "human":
            action_str = ev["action"].replace("_", " ")
            params = ev.get("params", {})
            if params:
                extras = ", ".join(f'{k.replace("_"," ")} {v}' for k, v in params.items())
                action_str = f"{action_str} ({extras})"
            rows.append({
                "ts": f"{int(ev['t'] // 60):02d}:{int(ev['t'] % 60):02d}",
                "actor": "H",
                "action": action_str,
                "trigger": "",
            })
        elif ev["actor"] == "cat" and ev.get("cat_id") == cat_id:
            rows.append({
                "ts": f"{int(ev['t'] // 60):02d}:{int(ev['t'] % 60):02d}",
                "actor": "C",
                "action": ev["action"].replace("_", " "),
                "trigger": f"← {ev['trigger'].replace('_', ' ')}" if ev.get("trigger") else "",
            })
    return rows[:12]


def _derive_status(cat_id: str, trust_arc: list[int]) -> str:
    """Generate a short status string from the trust arc and persona."""
    final = trust_arc[-1] if trust_arc else 0
    delta = final - trust_arc[0] if trust_arc else 0
    dips = sum(1 for i in range(1, len(trust_arc)) if trust_arc[i] < trust_arc[i - 1])

    if cat_id == "mewi":
        if dips >= 2:
            return f"Ended at {final}. Had setbacks — she remembers sudden movements."
        return f"Steady trust of {final}. Reads you before you enter her space."
    if cat_id == "miso":
        if delta > 20:
            return f"Trust {final}. Approached you without food present by the end."
        return f"Trust {final}. Consistent — comes for food, stays for warmth."
    if cat_id == "yuzu":
        if delta < 0:
            return f"Net trust: {final}. She tested you, you passed once, then she lost interest."
        return f"Trust {final}. Unpredictable. Passed her provocation test."
    if cat_id == "haru":
        if dips >= 1:
            return f"Trust {final}. Withdrew when your mood shifted — she noticed before you did."
        return f"Trust {final}. Offered presence quietly. Slow to enter, slow to leave."
    return f"Trust {final}."


def _human_phrase(events: list[dict]) -> str:
    human_actions = [
        ACTION_COPY.get(ev["action"], ev["action"].replace("_", " "))
        for ev in events
        if ev.get("actor") == "human"
    ]
    if not human_actions:
        return "you stayed mostly unreadable"
    if len(human_actions) == 1:
        return f"you {human_actions[0]}"
    return f"you {human_actions[0]}, then {human_actions[-1]}"


def _cat_phrase(events: list[dict], cat_id: str) -> str:
    cat_actions = [
        CAT_ACTION_COPY.get(ev["action"], ev["action"].replace("_", " "))
        for ev in events
        if ev.get("actor") == "cat" and ev.get("cat_id") == cat_id
    ]
    if not cat_actions:
        return ""
    if len(cat_actions) == 1:
        return cat_actions[0]
    return f"{cat_actions[0]}, then {cat_actions[-1]}"


def _cat_session_moments(sessions: list[dict], cat_id: str, trust_arc: list[int]) -> list[dict]:
    moments: list[dict] = []
    copy = CAT_NARRATIVE[cat_id]
    peak = max(trust_arc) if trust_arc else 0

    for i, sess in enumerate(sessions):
        prev = trust_arc[i - 1] if i > 0 else 0
        current = trust_arc[i] if i < len(trust_arc) else prev
        delta = current - prev
        events = sess["events"]
        cat_events = [e for e in events if e.get("actor") == "cat" and e.get("cat_id") == cat_id]
        cat_actions = {e["action"] for e in cat_events}

        if delta < 0:
            sentence = copy["dip"]
        elif "eat" in cat_actions:
            sentence = copy["food"]
        elif cat_actions & {"sit", "groom", "approach", "nod_head"}:
            sentence = copy["calm"] if delta <= 0 else copy["positive"]
        elif cat_actions & {"alert", "flee"}:
            sentence = copy["caution"]
        elif not cat_events:
            sentence = copy["absent"]
        elif delta > 0:
            sentence = copy["positive"]
        else:
            sentence = copy["flat"]

        human = _human_phrase(events)
        cat = _cat_phrase(events, cat_id)
        detail = f"{sentence} In the trace, {human}"
        if cat:
            detail += f"; {CAT_META[cat_id]['name']} {cat}"
        detail += f". Trust ended this session at {current}."

        milestone = None
        highlight = False
        if delta > 0:
            milestone = f"Trust +{delta}"
            highlight = True
        if current == peak and current > 0:
            milestone = "Highest trust so far" if milestone is None else f"{milestone} · highest so far"

        moments.append({
            "session": f"Session {sess['session_index']}",
            "event": detail,
            "highlight": highlight,
            "milestone": milestone,
        })

    return moments


def _session_timeline(sessions: list[dict], cat_trust_arcs: dict[str, list[int]]) -> list[dict]:
    timeline: list[dict] = []
    previous = {cat_id: 0 for cat_id in CAT_META}

    for sess_idx, sess in enumerate(sessions):
        idx = sess["session_index"]
        events = sess["events"]
        trust_now = {cat_id: cat_trust_arcs[cat_id][sess_idx] for cat_id in CAT_META}
        changed = {
            cat_id: trust_now[cat_id] - previous.get(cat_id, 0)
            for cat_id in CAT_META
        }
        active = [cat_id for cat_id, value in trust_now.items() if value > 0 or changed[cat_id] != 0]
        human = _human_phrase(events)
        cat_bits = []

        for cat_id in active:
            cat_events = [e for e in events if e.get("actor") == "cat" and e.get("cat_id") == cat_id]
            if not cat_events and trust_now[cat_id] <= 0:
                continue
            name = CAT_META[cat_id]["name"]
            delta = changed[cat_id]
            action = _cat_phrase(events, cat_id)
            if action:
                cat_bits.append(f"{name} {action} and ended at trust {trust_now[cat_id]}")
            elif trust_now[cat_id] > 0:
                cat_bits.append(f"{name} held trust {trust_now[cat_id]}")
            elif delta < 0:
                cat_bits.append(f"{name} withdrew to trust {trust_now[cat_id]}")

        if cat_bits:
            event = f"{human.capitalize()}. " + "; ".join(cat_bits) + "."
        else:
            event = f"{human.capitalize()}. No cat recorded a trust change."

        positive = [cat_id for cat_id, delta in changed.items() if delta > 0]
        milestone = None
        if len(positive) >= 2:
            milestone = "Multiple bonds active"
        elif positive:
            cat_id = positive[0]
            milestone = f"{CAT_META[cat_id]['name']} trust +{changed[cat_id]}"

        timeline.append({
            "session": f"Session {idx}",
            "event": event,
            "highlight": bool(positive),
            "milestone": milestone,
        })
        previous = trust_now

    return timeline


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _user_profile(user_id: str, users: dict[str, dict[str, Any]]) -> dict[str, Any]:
    profile = users.get(user_id, {})
    display_name = profile.get("display_name") or profile.get("handle") or user_id
    handle = profile.get("handle") or display_name
    return {
        "id": user_id,
        "display_name": display_name,
        "handle": handle,
        "report_slug": profile.get("report_slug", user_id),
    }


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _player_action_family(action: str) -> str:
    spec = PLAYER_CAT_ACTION_SCHEMA.get(action)
    if spec:
        return spec["family"]
    return "unknown" if action.startswith("player_") else ""


def _is_player_action_event(event: dict[str, Any]) -> bool:
    action = str(event.get("action") or "")
    return event.get("actor_type") == "player_cat" or action.startswith("player_")


def _phase_rank(event: dict[str, Any]) -> int:
    phase = str(event.get("phase") or "").lower()
    if phase == "completed":
        return 4
    if phase == "committed":
        return 3
    if phase == "started":
        return 2
    return 1


def _session_namespace(session: dict[str, Any], order: int) -> str:
    session_id = str(session.get("session_id") or "")
    session_index = str(session.get("session_index") or "")
    timestamp = str(session.get("timestamp_start") or "")
    return f"{order}:{session_id}:{session_index}:{timestamp}"


def _primary_player_actions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one row per player action episode.

    Unity can emit started/committed/completed rows for the same correlation id.
    For statistics, count the most complete phase only; otherwise a single click
    would look like three attachment bids.
    """
    chosen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for order, sess in enumerate(sessions):
        session_key = _session_namespace(sess, order)
        for event in sess.get("events", []):
            if not _is_player_action_event(event):
                continue
            action = str(event.get("action") or "")
            target_id = str(event.get("target_id") or event.get("params", {}).get("target_id") or "")
            correlation_id = str(event.get("correlation_id") or event.get("event_id") or "")
            key = (session_key, correlation_id, action, target_id)
            current = chosen.get(key)
            if current is None or _phase_rank(event) >= _phase_rank(current):
                chosen[key] = {**event, "_session_key": session_key, "_session_order": order}
    return sorted(
        chosen.values(),
        key=lambda event: (
            event.get("_session_order") or 0,
            event.get("t") or 0,
            event.get("event_id") or "",
        ),
    )


def _pct_map(counts: dict[str, int], keys: tuple[str, ...] | list[str]) -> dict[str, int]:
    total = sum(counts.values())
    if total <= 0:
        return {key: 0 for key in keys}
    return {key: round(counts.get(key, 0) / total * 100) for key in keys}


def _interaction_signature(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    actions = _primary_player_actions(sessions)
    action_counts: dict[str, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)
    target_counts: dict[str, int] = defaultdict(int)
    ignored_actions: list[str] = []

    for event in actions:
        action = str(event.get("action") or "")
        family = str(event.get("action_family") or _player_action_family(action) or "unknown")
        target_id = str(event.get("target_id") or event.get("params", {}).get("target_id") or "")
        action_counts[action] += 1
        family_counts[family] += 1
        if target_id:
            target_counts[target_id] += 1
        if family == "unknown" and action not in ignored_actions:
            ignored_actions.append(action)

    return {
        "action_counts": dict(sorted(action_counts.items())),
        "action_family_pct": _pct_map(family_counts, PLAYER_ACTION_FAMILIES),
        "target_distribution": dict(sorted(_pct_map(target_counts, sorted(target_counts)).items())),
        "ignored_actions": sorted(ignored_actions),
    }


def _has_legacy_human_actions(sessions: list[dict[str, Any]]) -> bool:
    return any(
        event.get("actor") == "human" and event.get("actor_type") != "player_cat"
        for session in sessions
        for event in session.get("events", [])
    )


def _has_player_actions(interaction_signature: dict[str, Any]) -> bool:
    action_counts = interaction_signature.get("action_counts") or {}
    return sum(int(value or 0) for value in action_counts.values()) > 0


def _gesture_response_chains(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events_by_session = {
        _session_namespace(sess, order): sess.get("events", [])
        for order, sess in enumerate(sessions)
    }
    player_events = _primary_player_actions(sessions)
    chains: list[dict[str, Any]] = []

    for event in player_events:
        session_events = events_by_session.get(str(event.get("_session_key") or ""), [])
        event_id = str(event.get("event_id") or "")
        correlation_id = str(event.get("correlation_id") or "")
        action = str(event.get("action") or "")
        target_id = str(event.get("target_id") or event.get("params", {}).get("target_id") or "")
        t0 = float(event.get("t") or 0)

        delivered = next(
            (
                candidate for candidate in session_events
                if candidate.get("actor_type") == "system"
                and candidate.get("action") == "social_stimulus_delivered"
                and candidate.get("correlation_id") == correlation_id
                and (
                    candidate.get("params", {}).get("source_event_id") == event_id
                    or not event_id
                )
            ),
            None,
        )

        reaction = next(
            (
                candidate for candidate in session_events
                if candidate.get("actor_type") == "cat"
                and candidate.get("correlation_id") == correlation_id
                and float(candidate.get("t") or 0) >= t0
                and (
                    candidate.get("params", {}).get("source_event_id") == event_id
                    or not event_id
                )
            ),
            None,
        )

        trust_delta = None
        reaction_latency = None
        if reaction is not None:
            before = reaction.get("trust_before")
            after = reaction.get("trust_after")
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                trust_delta = after - before
            reaction_latency = round(float(reaction.get("t") or 0) - t0, 2)

        evidence_ids = [value for value in (
            event_id,
            delivered.get("event_id") if delivered else "",
            reaction.get("event_id") if reaction else "",
        ) if value]

        chains.append({
            "correlation_id": correlation_id,
            "source_event_id": event_id,
            "player_action": action,
            "action_family": event.get("action_family") or _player_action_family(action) or "unknown",
            "target_id": target_id,
            "delivered": delivered is not None,
            "cat_reaction": reaction.get("action") if reaction else "",
            "reaction_event_id": reaction.get("event_id") if reaction else "",
            "reaction_latency_s": reaction_latency,
            "trust_delta": trust_delta,
            "phase": event.get("phase") or "",
            "status": reaction.get("status") if reaction else "",
            "confidence": event.get("params", {}).get("confidence", -1),
            "facing_dot": event.get("params", {}).get("facing_dot", -1),
            "evidence_event_ids": evidence_ids,
        })

    return chains


def _score(value: float) -> int:
    return max(0, min(100, round(value)))


def _attachment_features(
    interaction_signature: dict[str, Any],
    chains: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    families = interaction_signature.get("action_family_pct") or {}
    action_counts = interaction_signature.get("action_counts") or {}
    if sum(int(value or 0) for value in action_counts.values()) <= 0:
        return [
            {"label": "Attuned soft bids", "value": 0, "evidence_event_ids": []},
            {"label": "Respect for distance", "value": 0, "evidence_event_ids": []},
            {"label": "Repair after rupture", "value": 0, "evidence_event_ids": []},
            {"label": "Pursuit pressure", "value": 0, "evidence_event_ids": []},
            {"label": "Threat / intrusion pressure", "value": 0, "evidence_event_ids": []},
            {"label": "Exploration over reassurance", "value": 0, "evidence_event_ids": []},
        ]

    total_chains = max(len(chains), 1)
    delivered_pct = sum(1 for chain in chains if chain.get("delivered")) / total_chains * 100
    responded_pct = sum(1 for chain in chains if chain.get("cat_reaction")) / total_chains * 100
    positive_pct = sum(1 for chain in chains if (chain.get("trust_delta") or 0) > 0) / total_chains * 100
    negative_pct = sum(1 for chain in chains if (chain.get("trust_delta") or 0) < 0) / total_chains * 100

    soft_bid = families.get("affiliative_bid", 0)
    calm = families.get("calm_presence", 0)
    cautious = families.get("cautious_investigation", 0)
    explore = families.get("exploration_resource", 0)
    boundary = families.get("boundary_refusal", 0)
    threat = families.get("intrusion_threat", 0)
    fear = families.get("fear_startle_shutdown", 0)
    push_attack_count = action_counts.get("player_push", 0) + action_counts.get("player_attack", 0)

    evidence = [
        event_id
        for chain in chains[:3]
        for event_id in chain.get("evidence_event_ids", [])
    ]

    return [
        {
            "label": "Attuned soft bids",
            "value": _score((soft_bid * 0.45) + (delivered_pct * 0.2) + (responded_pct * 0.2) + (positive_pct * 0.15)),
            "evidence_event_ids": evidence[:4],
        },
        {
            "label": "Respect for distance",
            "value": _score(calm + cautious + (100 - threat - fear - negative_pct) * 0.35),
            "evidence_event_ids": evidence[:4],
        },
        {
            "label": "Repair after rupture",
            "value": _score((positive_pct * 0.55) + (responded_pct * 0.25) + (calm * 0.2)),
            "evidence_event_ids": evidence[:4],
        },
        {
            "label": "Pursuit pressure",
            "value": _score((soft_bid * 0.4) + (negative_pct * 0.4) + (boundary * 0.2)),
            "evidence_event_ids": evidence[:4],
        },
        {
            "label": "Threat / intrusion pressure",
            "value": _score(threat + push_attack_count * 12 + negative_pct * 0.2),
            "evidence_event_ids": evidence[:4],
        },
        {
            "label": "Exploration over reassurance",
            "value": _score(explore + cautious * 0.5 + (100 - soft_bid) * 0.15),
            "evidence_event_ids": evidence[:4],
        },
    ]


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw v1/v2 event rows into the processor shape.

    Raw v2 keeps richer identity/lifecycle fields at the row top level. Preserve
    ``actor_type`` for the v2 interaction feature layer, while keeping the
    legacy ``actor == human`` compatibility view for old charts.
    """
    normalized = dict(event)
    params = normalized.get("params")
    normalized["params"] = dict(params) if isinstance(params, dict) else {}

    target_id = normalized.get("target_id")
    if target_id and not normalized["params"].get("target_id"):
        normalized["params"]["target_id"] = target_id

    action = str(normalized.get("action") or "")
    actor = normalized.get("actor")
    normalized["actor_type"] = actor
    family = _player_action_family(action)
    if family:
        normalized["action_family"] = family

    if actor == "player_cat":
        normalized["actor"] = "human"
    elif actor == "cat" and not normalized.get("cat_id"):
        actor_id = normalized.get("actor_id")
        if actor_id:
            normalized["cat_id"] = str(actor_id).strip().lower()

    return normalized


def normalize_session(session: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(session)
    normalized["events"] = [
        normalize_event(event)
        for event in _safe_list(normalized.get("events"))
        if isinstance(event, dict)
    ]
    normalized["multi_cat_encounters"] = _safe_list(normalized.get("multi_cat_encounters"))
    return normalized


def session_sort_key(session: dict[str, Any]) -> tuple[int, str, str]:
    try:
        idx = int(session.get("session_index") or 0)
    except (TypeError, ValueError):
        idx = 0
    return (
        idx,
        str(session.get("timestamp_start") or ""),
        str(session.get("session_id") or ""),
    )


# ── main processor ────────────────────────────────────────────────────────────

def process_report(
    user_id: str,
    sessions: list[dict[str, Any]],
    users: dict[str, dict[str, Any]] | None = None,
    report_overrides: dict[str, Any] | None = None,
    attachment_mode: str = ATTACHMENT_MODE_DEFAULT,
) -> dict[str, Any]:
    """Derive the website-ready processed report for one user.

    ``sessions`` is the list of raw ``session`` objects (the inner ``session``
    of each ``mewi.report.raw.v1`` or ``mewi.report.raw.v2`` payload).
    ``users`` is the parsed ``user_info.json`` users map. ``report_overrides``
    is the optional demo escape hatch that deep-merges over the derived values.

    ``attachment_mode`` is accepted only for compatibility with older fixtures;
    this Lambda processor always builds the deterministic block. The handler may
    replace ``attachment_analysis`` with a Claude/RAG-derived block after this
    full shape is built.
    """
    report_overrides = report_overrides or {}
    sessions = [normalize_session(s) for s in sessions if isinstance(s, dict)]
    sessions = sorted(sessions, key=session_sort_key)
    user = _user_profile(user_id, users or {})
    n_sessions = len(sessions)

    # ── per-cat trust arc (one value per session) ─────────────────────────────
    cat_trust_arcs: dict[str, list[int]] = {k: [] for k in CAT_META}
    for sess in sessions:
        for cat_id in CAT_META:
            trust = _session_trust(sess["events"], cat_id)
            cat_trust_arcs[cat_id].append(trust)

    # ── per-cat trust deltas ──────────────────────────────────────────────────
    cat_deltas: dict[str, int] = {}
    for cat_id, arc in cat_trust_arcs.items():
        if arc:
            cat_deltas[cat_id] = arc[-1] - arc[0]

    # ── global metrics ────────────────────────────────────────────────────────
    all_events = [ev for s in sessions for ev in s["events"]]
    action_counts = _human_action_counts(sessions)
    latencies = [lat for s in sessions for lat in _reaction_latencies(s["events"])]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    avg_trust = round(sum(arc[-1] for arc in cat_trust_arcs.values() if arc) / len(CAT_META)) if sessions else 0
    total_events = len(all_events)
    primary_bond = max(cat_trust_arcs, key=lambda k: cat_trust_arcs[k][-1] if cat_trust_arcs[k] else 0)
    patience_pct = min(round(action_counts.get("sit", 0) + action_counts.get("wait", 0) +
                             action_counts.get("stop_moving", 0)) * 3, 100)

    # ── per-cat detailed blocks ───────────────────────────────────────────────
    cats_out: dict[str, Any] = {}
    for cat_id, meta in CAT_META.items():
        arc = cat_trust_arcs[cat_id]
        delta = cat_deltas.get(cat_id, 0)
        delta_str = f"+{delta}" if delta >= 0 else str(delta)

        cat_events = [e for e in all_events if e.get("cat_id") == cat_id]
        total_cat = max(len(cat_events), 1)

        approach_acc = sum(1 for e in cat_events if e["action"] in ("sit", "eat", "groom", "nod_head"))
        food_acc     = sum(1 for e in cat_events if e["action"] == "eat")
        vocalized    = sum(1 for e in cat_events if e["action"] == "vocalize")
        zone_allowed = sum(1 for e in cat_events if e["action"] not in ("flee", "alert"))
        cat_init     = sum(1 for e in cat_events if e.get("trigger") in ("cat_initiated", "proximity_comfort"))

        def _pct(n: int, _total: int = total_cat) -> int:
            return min(round(n / _total * 100 * 3), 100)

        if cat_id == "yuzu":
            bars = [
                {"label": "Approach accepted",        "value": _pct(approach_acc)},
                {"label": "Provocation without retreat","value": _pct(sum(1 for e in cat_events if e["action"] in ("bat","nod_head")))},
                {"label": "Vocalized at you",         "value": _pct(vocalized)},
                {"label": "Zone entry allowed",       "value": _pct(zone_allowed)},
                {"label": "Cat-initiated approach",   "value": _pct(cat_init)},
            ]
        elif cat_id == "haru":
            bars = [
                {"label": "Presence offered (unprompted)", "value": _pct(cat_init + approach_acc)},
                {"label": "Stayed when you moved",         "value": _pct(zone_allowed)},
                {"label": "Vocalized at you",              "value": _pct(vocalized)},
                {"label": "Zone entry allowed",            "value": _pct(zone_allowed)},
                {"label": "Direct eye contact held",       "value": _pct(approach_acc)},
            ]
        else:
            bars = [
                {"label": "Approach accepted",  "value": _pct(approach_acc)},
                {"label": "Food accepted",      "value": _pct(food_acc)},
                {"label": "Vocalized at you",   "value": _pct(vocalized)},
                {"label": "Zone entry allowed", "value": _pct(zone_allowed)},
                {"label": "Cat-initiated contact", "value": _pct(cat_init)},
            ]

        cats_out[cat_id] = {
            **meta,
            "trust_arc": arc,
            "delta": delta_str,
            "status": _derive_status(cat_id, arc),
            "bars": bars,
            "sequence_log": _session_events_for_log(sessions, cat_id) if sessions else [],
            "moments": _cat_session_moments(sessions, cat_id, arc),
        }

    timeline = _session_timeline(sessions, cat_trust_arcs)
    attachment_profile = _attachment_profile(action_counts, cat_trust_arcs)
    interaction_signature = _interaction_signature(sessions)
    gesture_response_chains = _gesture_response_chains(sessions)
    attachment_features = (
        []
        if not _has_player_actions(interaction_signature) and _has_legacy_human_actions(sessions)
        else _attachment_features(interaction_signature, gesture_response_chains)
    )

    result = {
        "user_id": user_id,
        "user": user,
        "meta": {
            "sessions": n_sessions,
            "total_events": total_events,
            "last_seen": sessions[-1]["timestamp_start"][:10] if sessions else "",
        },
        "summary": {
            "avg_trust_gained": avg_trust,
            "primary_bond": primary_bond,
            "avg_reaction_latency_s": avg_latency,
            "patience_pct": patience_pct,
        },
        "cats": cats_out,
        "radar": _radar_values(action_counts),
        "attention_pct": _attention_pct(sessions),
        "multi_cat_encounters": _multi_cat_encounters(sessions),
        "interaction_signature": interaction_signature,
        "gesture_response_chains": gesture_response_chains,
        "attachment_features": attachment_features,
        "attachment_profile": attachment_profile,
        "attachment_analysis": _run_attachment_analysis(
            attachment_mode,
            attachment_profile,
            cat_trust_arcs,
            user_id=user_id,
            sessions=sessions,
            attachment_features=attachment_features,
            interaction_signature=interaction_signature,
        ),
        "timeline": timeline,
    }

    # Curated demo/report data can override derived values while keeping the same
    # raw-log pipeline. Useful for presentation-grade sample reports.
    if report_overrides:
        result = _deep_merge(result, report_overrides)

    return result
