from uuid import uuid4

from app.models.attachment import (
    AttachmentEventType,
    CatAssignedType,
    RawAttachmentEvent,
)
from app.services.attachment.preprocess import preprocess_attachment_session


def _event(session_id, event, t, distance=None):
    return RawAttachmentEvent(
        session_id=session_id,
        cat_id="milo",
        event=event,
        t=t,
        distance=distance,
    )


def test_preprocess_computes_strange_situation_features() -> None:
    session_id = uuid4()
    events = [
        _event(session_id, AttachmentEventType.PLAYER_NEAR, 0.0, 1.5),
        _event(session_id, AttachmentEventType.CAT_WITHDREW, 10.0, 1.8),
        _event(session_id, AttachmentEventType.PLAYER_APPROACHED, 14.0, 1.2),
        _event(session_id, AttachmentEventType.PLAYER_RETREATED, 24.0, 3.5),
        _event(session_id, AttachmentEventType.PLAYER_LEFT, 40.0, 8.0),
        _event(session_id, AttachmentEventType.PLAYER_RETURNED_AFTER_ABSENCE, 60.0, 6.0),
        _event(session_id, AttachmentEventType.PLAYER_APPROACHED, 63.0, 2.0),
        _event(session_id, AttachmentEventType.PLAYER_INTERACTED, 65.0, 1.0),
    ]

    features = preprocess_attachment_session(
        events,
        cat_assigned_type=CatAssignedType.AVOIDANT,
    )

    assert features.session_id == session_id
    assert features.cat_id == "milo"
    assert features.cat_assigned_type == CatAssignedType.AVOIDANT
    assert features.reapproach_latency_mean == 4.0
    assert features.pursuit_ratio == 0.5
    assert features.time_near_ratio == 0.625
    assert features.reunion_response == 1.0
    assert features.withdrawal_tolerance == 14.0
    assert features.n_events == 8
