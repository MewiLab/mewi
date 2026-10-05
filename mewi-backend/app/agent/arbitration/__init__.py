"""Thin domain proposal layer for intent arbitration.

These modules do not choose the final intent. They surface compact,
deterministic hints from social context, exploration memory, and need history
so the LLM selector can arbitrate without growing custom planner functions.
"""
from __future__ import annotations

from app.agent.arbitration.exploration_proposal import (
    exploration_proposal_lines,
    propose_exploration_intent,
)
from app.agent.arbitration.need_assessment import NeedAssessment, assess_needs, propose_need_intent
from app.agent.arbitration.social_proposal import propose_social_intent, social_proposal_lines

__all__ = [
    "NeedAssessment",
    "assess_needs",
    "exploration_proposal_lines",
    "propose_exploration_intent",
    "propose_need_intent",
    "propose_social_intent",
    "social_proposal_lines",
]
