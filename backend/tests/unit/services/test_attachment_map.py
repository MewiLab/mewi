from uuid import uuid4

from app.models.attachment import (
    AttachmentConfidence,
    AttachmentSessionFeatures,
    CatAssignedType,
    PlayerAttachmentEstimate,
)
from app.services.attachment_map import atf


def _features(**overrides):
    values = {
        "session_id": uuid4(),
        "cat_id": "milo",
        "cat_assigned_type": CatAssignedType.AVOIDANT,
        "reapproach_latency_mean": 3.0,
        "pursuit_ratio": 0.8,
        "time_near_ratio": 0.7,
        "reunion_response": 0.9,
        "withdrawal_tolerance": 14.0,
        "n_events": 20,
    }
    values.update(overrides)
    return AttachmentSessionFeatures(**values)


def test_atf_declines_to_classify_sparse_sessions() -> None:
    result = atf(_features(n_events=3))

    assert result.player_attachment_estimate == PlayerAttachmentEstimate.UNDETERMINED
    assert result.confidence == AttachmentConfidence.LOW
    assert all(score == 0.0 for score in result.scores.values())


def test_atf_keeps_assigned_cat_type_but_infers_player_type() -> None:
    result = atf(_features(cat_assigned_type=CatAssignedType.AVOIDANT))

    assert result.cat_assigned_type == CatAssignedType.AVOIDANT
    assert result.player_attachment_estimate in {
        PlayerAttachmentEstimate.SECURE,
        PlayerAttachmentEstimate.ANXIOUS,
        PlayerAttachmentEstimate.AVOIDANT,
        PlayerAttachmentEstimate.DISORGANIZED,
    }
    assert round(sum(result.scores.values()), 1) == 1.0
    assert result.confidence == AttachmentConfidence.LOW
    assert result.rule_trace
