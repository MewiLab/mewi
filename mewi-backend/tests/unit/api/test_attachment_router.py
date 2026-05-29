from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_settings, get_supabase
from app.core.config import Settings
from app.main import create_app


def _mock_supabase():
    builder = MagicMock()
    builder.insert.return_value = builder
    builder.upsert.return_value = builder
    builder.execute.return_value = MagicMock(data=[{"id": "row"}])

    client = MagicMock()
    client.table.return_value = builder
    client._builder = builder
    return client


def _settings():
    return Settings(
        supabase_url="http://fake-supabase",
        supabase_publishable_key="fake-anon-key",
        supabase_secret_key="fake-secret-key",
        openai_api_key="fake-openai-key",
    )


def test_attachment_session_endpoint_returns_result_and_persists_layers() -> None:
    settings = _settings()
    supabase = _mock_supabase()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_supabase] = lambda: supabase
    client = TestClient(app, headers={"X-API-Key": settings.API_SECRET_TOKEN})
    session_id = str(uuid4())

    response = client.post("/api/v1/attachment/session", json={
        "session_id": session_id,
        "cat_id": "milo",
        "cat_assigned_type": "avoidant",
        "events": [
            {"event": "player_near", "t": 0.0, "distance": 1.4},
            {"event": "cat_withdrew", "t": 10.0, "distance": 1.8},
            {"event": "player_approached", "t": 13.0, "distance": 1.2},
            {"event": "player_retreated", "t": 26.0, "distance": 4.0},
            {"event": "player_left", "t": 40.0, "distance": 7.0},
            {"event": "player_returned_after_absence", "t": 60.0, "distance": 6.0},
            {"event": "player_approached", "t": 63.0, "distance": 2.0},
            {"event": "player_interacted", "t": 66.0, "distance": 1.0},
        ],
    })

    assert response.status_code == 201
    data = response.json()
    assert data["session_id"] == session_id
    assert data["cat_id"] == "milo"
    assert data["cat_assigned_type"] == "avoidant"
    assert data["confidence"] == "low"
    assert data["features"]["n_events"] == 8
    assert set(data["scores"]) == {"secure", "anxious", "avoidant", "disorganized"}

    assert [call.args[0] for call in supabase.table.call_args_list] == [
        "attachment_raw_events",
        "attachment_session_features",
        "attachment_results",
    ]

    app.dependency_overrides.clear()
