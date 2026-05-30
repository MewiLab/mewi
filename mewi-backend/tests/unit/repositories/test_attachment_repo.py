from unittest.mock import MagicMock
from uuid import uuid4

from app.models.attachment import (
    AttachmentSessionFeatures,
    CatAssignedType,
    PlayerAttachmentEstimate,
    RawAttachmentEvent,
    AttachmentEventType,
)
from app.repositories.attachment_repo import AttachmentRepository
from app.services.attachment.map import atf


def _mock_supabase():
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.upsert.return_value = builder
    builder.execute.return_value = MagicMock(data=[{"id": "row"}])

    client = MagicMock()
    client.table.return_value = builder
    client._builder = builder
    return client


def test_repository_persists_raw_features_and_result_shapes() -> None:
    db = _mock_supabase()
    repo = AttachmentRepository(db)
    session_id = uuid4()
    raw = [
        RawAttachmentEvent(
            session_id=session_id,
            cat_id="milo",
            event=AttachmentEventType.CAT_WITHDREW,
            t=1.0,
            distance=2.0,
        )
    ]
    features = AttachmentSessionFeatures(
        session_id=session_id,
        cat_id="milo",
        cat_assigned_type=CatAssignedType.AVOIDANT,
        n_events=1,
    )
    result = atf(features)

    repo.save_raw_events(raw, cat_assigned_type=CatAssignedType.AVOIDANT)
    repo.save_features(features)
    repo.save_result(result)

    assert db.table.call_args_list[0].args[0] == "attachment_raw_events"
    assert db.table.call_args_list[1].args[0] == "attachment_session_features"
    assert db.table.call_args_list[2].args[0] == "attachment_results"

    raw_rows = db._builder.insert.call_args.args[0]
    assert raw_rows[0]["cat_assigned_type"] == "avoidant"

    result_row = db._builder.upsert.call_args.args[0]
    assert result_row["player_attachment_estimate"] == PlayerAttachmentEstimate.UNDETERMINED.value
    assert result_row["features"]["cat_assigned_type"] == "avoidant"
