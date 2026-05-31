from __future__ import annotations

from typing import Any

from app.agent.mind.intents import INTENT_SOCIALIZE
from app.agent.prompts.sections import clean_text
from app.social.service import SocialService


async def execute_intent_effects(
    state: dict[str, Any],
    *,
    social: SocialService | None,
) -> dict[str, Any]:
    """Run backend-owned side effects for the selected intent."""

    decision = state.get("intent_decision") if isinstance(state, dict) else {}
    if not isinstance(decision, dict):
        decision = {}

    dialogue = _list_dicts(state.get("dialogue"))
    social_context = state.get("social_context") if isinstance(state.get("social_context"), dict) else {}
    tool_results: list[dict[str, Any]] = []
    social_effects: list[dict[str, Any]] = []
    wake_targets: list[str] = []

    if social is not None:
        resolved = social.resolve_observed_bids(
            clean_text(state.get("creature_id")),
            delivered_inbox=_list_dicts(social_context.get("delivered_inbox")),
            selected_intent=clean_text(decision.get("intent")),
            target_id=clean_text(decision.get("target_id")),
            spoke=_has_spoken_social_act(decision),
        )
        if resolved:
            tool_results.append({"tool": "social.resolve_observed_bids", "status": "done"})
            social_effects.extend({"type": "bid_resolved", **item} for item in resolved)

    if social is not None and clean_text(decision.get("intent")) == INTENT_SOCIALIZE:
        social_act = decision.get("social_act") if isinstance(decision.get("social_act"), dict) else {}
        say = clean_text(social_act.get("say"))
        if say:
            result = await social.publish_turn(
                clean_text(state.get("creature_id")),
                say=say,
                target=clean_text(decision.get("target_id")),
                tone=clean_text(social_act.get("tone")) or clean_text(decision.get("mood")) or "neutral",
                act_kind=clean_text(social_act.get("kind")) or "message",
                expects_reply=bool(social_act.get("expects_reply")),
            )
            published_dialogue = result.dialogue_for_unity()
            dialogue.extend(published_dialogue)
            social_context = _merge_social_context(social_context, result.to_prompt_context())
            wake_targets.extend(_wake_targets(published_dialogue, state.get("creature_id")))
            tool_results.append({"tool": "social.publish_turn", "status": "done"})
            social_effects.append({
                "type": "social_publish",
                "target_id": clean_text(decision.get("target_id")),
                "say": say,
            })

    return {
        "dialogue": dialogue,
        "social_context": social_context,
        "tool_results": tool_results,
        "social_effects": social_effects,
        "wake_targets": _dedupe(wake_targets),
    }


def _merge_social_context(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base) if isinstance(base, dict) else {}
    for key, value in update.items():
        if key == "delivered_inbox":
            merged[key] = _list_dicts(merged.get(key)) + _list_dicts(value)
        elif key == "social_feedback":
            merged[key] = _list_dicts(merged.get(key)) + _list_dicts(value)
        elif key == "relationships":
            merged[key] = _list_dicts(value) or _list_dicts(merged.get(key))
        elif key == "decision":
            if isinstance(value, dict) and value.get("note") != "no presence":
                merged[key] = value
        elif value is not None:
            merged[key] = value
    return merged


def _has_spoken_social_act(decision: dict[str, Any]) -> bool:
    social_act = decision.get("social_act")
    return isinstance(social_act, dict) and bool(clean_text(social_act.get("say")))


def _wake_targets(dialogue: list[dict[str, Any]], creature_id: Any) -> list[str]:
    own_id = clean_text(creature_id)
    targets: list[str] = []
    for item in dialogue:
        if clean_text(item.get("from")) != own_id:
            continue
        target = clean_text(item.get("target") or item.get("target_id"))
        if target:
            targets.append(target)
    return targets


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in out:
            out.append(text)
    return out
