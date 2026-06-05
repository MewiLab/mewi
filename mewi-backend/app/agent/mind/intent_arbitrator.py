from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.agent.mind.intents import (
    INTENT_EXPLORE,
    INTENT_IDLE,
    INTENT_INVESTIGATE,
    INTENT_REST,
    INTENT_SAFETY,
    INTENT_SEEK_FOOD,
    INTENT_SEEK_PLAYER,
    INTENT_SOCIALIZE,
    normalize_intent,
)
from app.agent.prompts.sections import clean_text


INTENT_PRIORITY = {
    INTENT_SAFETY: 100,
    INTENT_SEEK_FOOD: 80,
    INTENT_REST: 70,
    INTENT_SOCIALIZE: 60,
    INTENT_SEEK_PLAYER: 55,
    INTENT_INVESTIGATE: 45,
    INTENT_EXPLORE: 40,
    INTENT_IDLE: 0,
}

DOMAIN_PRIORITY = {
    "need": 30,
    "social": 20,
    "exploration": 10,
}


def select_intent_from_proposals(proposals: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse domain proposals into one ActionFSM-style directive."""

    valid = [_normalise_proposal(item) for item in proposals if isinstance(item, dict)]
    valid = [item for item in valid if item["intent"]]
    if not valid:
        return _idle_decision("No valid domain proposals were returned.")

    non_idle = [item for item in valid if item["intent"] != INTENT_IDLE]
    candidates = non_idle or valid
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        grouped[item["intent"]].append(item)

    selected_intent = max(
        grouped,
        key=lambda intent: (len(grouped[intent]), INTENT_PRIORITY.get(intent, 0)),
    )
    selected_group = grouped[selected_intent]
    target_id = _select_target(selected_group)
    winner = _select_winning_proposal(selected_group, target_id)
    supporting_domains = _supporting_domains(selected_group)

    decision = {
        "intent": selected_intent,
        "target_id": target_id,
        "mood": winner.get("mood", ""),
        "style": winner.get("style", ""),
        "reasoning": winner.get("reasoning") or _reasoning(selected_intent, supporting_domains),
        "supporting_domains": supporting_domains,
        "confidence": _confidence(len(selected_group), len(valid)),
        "source_domain": winner.get("domain", ""),
    }

    social_act = _social_act(winner)
    if social_act:
        decision["social_act"] = social_act

    return decision


def _normalise_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    out = dict(proposal)
    out["intent"] = normalize_intent(out.get("intent"), default=INTENT_IDLE)
    out["domain"] = clean_text(out.get("domain"))
    out["target_id"] = clean_text(out.get("target_id") or out.get("target"))
    out["mood"] = clean_text(out.get("mood"))
    out["style"] = clean_text(out.get("style"))
    out["reasoning"] = clean_text(out.get("reasoning"))
    return out


def _select_target(proposals: list[dict[str, Any]]) -> str:
    targets = [clean_text(item.get("target_id")) for item in proposals if clean_text(item.get("target_id"))]
    if not targets:
        return ""
    counts = Counter(targets)
    return max(
        counts,
        key=lambda target: (
            counts[target],
            max(_proposal_score(item) for item in proposals if item.get("target_id") == target),
        ),
    )


def _select_winning_proposal(proposals: list[dict[str, Any]], target_id: str) -> dict[str, Any]:
    return max(
        proposals,
        key=lambda item: (
            bool(target_id and item.get("target_id") == target_id),
            bool(_social_act(item)),
            _proposal_score(item),
        ),
    )


def _proposal_score(proposal: dict[str, Any]) -> int:
    intent = clean_text(proposal.get("intent"))
    domain = clean_text(proposal.get("domain"))
    return INTENT_PRIORITY.get(intent, 0) + DOMAIN_PRIORITY.get(domain, 0)


def _supporting_domains(proposals: list[dict[str, Any]]) -> list[str]:
    domains: list[str] = []
    for item in proposals:
        domain = clean_text(item.get("domain"))
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _confidence(votes: int, total: int) -> str:
    if votes >= 3 or (total > 0 and votes == total):
        return "high"
    if votes == 2:
        return "medium"
    return "low"


def _reasoning(intent: str, supporting_domains: list[str]) -> str:
    if supporting_domains:
        return f"{intent} was supported by {', '.join(supporting_domains)}."
    return f"{intent} was selected from domain proposals."


def _social_act(proposal: dict[str, Any]) -> dict[str, Any]:
    raw = proposal.get("social_act")
    if not isinstance(raw, dict):
        say = clean_text(proposal.get("say"))
        tone = clean_text(proposal.get("tone"))
        raw = {"say": say, "tone": tone} if say or tone else {}

    say = clean_text(raw.get("say"))
    tone = clean_text(raw.get("tone"))
    kind = clean_text(raw.get("kind")) or "message"
    expects_reply = raw.get("expects_reply")
    return {
        "kind": kind,
        "say": say,
        "tone": tone,
        "expects_reply": bool(expects_reply) if expects_reply is not None else bool(say),
    } if say or tone or kind != "message" else {}


def _idle_decision(reasoning: str) -> dict[str, Any]:
    return {
        "intent": INTENT_IDLE,
        "target_id": "",
        "mood": "neutral",
        "style": "quiet pause",
        "reasoning": reasoning,
        "supporting_domains": [],
        "confidence": "low",
        "source_domain": "",
    }
