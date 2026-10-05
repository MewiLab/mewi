from app.api.routes.agent_router import router
from app.services.agent_tick.ws_session import _shared_websocket_plan_response


def test_only_shared_agent_websocket_route_is_registered():
    websocket_paths = {
        getattr(route, "path", "")
        for route in router.routes
        if getattr(route, "path", "").startswith("/agent/ws")
    }

    assert websocket_paths == {"/agent/ws"}


def test_shared_response_routes_by_original_creature_and_request():
    response = _shared_websocket_plan_response(
        {
            "job_id": "job-001",
            "creature_id": "wrong-cat",
            "request_id": "wrong-request",
            "status": "done",
            "tick": 3,
            "intent": {"intent": "SOCIALIZE", "target_id": "cat_b"},
            "plan_steps": [{"action": "wait", "target": "", "reason": "observe"}],
        },
        "cat_a",
        "req-001",
    )

    assert response["creature_id"] == "cat_a"
    assert response["request_id"] == "req-001"
    assert response["intent"]["intent"] == "SOCIALIZE"
