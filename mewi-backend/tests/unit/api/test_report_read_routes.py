from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_report_read_service, get_settings
from app.api.routes import report_router
from app.core.auth import create_report_read_token
from app.core.config import Settings
from app.models.report import ReportProduct
from app.services.report.service import ReportReadService
from app.services.report.store import ReportResultNotFound


SECRET = "test-report-read-secret-with-32-bytes"


class FakeResultStore:
    def __init__(self, reports: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._reports = reports

    def get(self, user_id: str, product: ReportProduct) -> dict[str, Any]:
        try:
            return self._reports[(user_id, product)]
        except KeyError as exc:
            raise ReportResultNotFound(f"{user_id}/{product}") from exc

    def list(self, product: ReportProduct) -> list[dict[str, Any]]:
        return [
            report
            for (user_id, report_product), report in self._reports.items()
            if report_product == product
        ]


def _report(user_id: str, display_name: str, last_seen: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "user": {
            "id": user_id,
            "display_name": display_name,
            "handle": user_id,
        },
        "meta": {
            "sessions": 2,
            "total_events": 12,
            "last_seen": last_seen,
        },
        "summary": {
            "primary_bond": "mewi",
        },
        "cats": {},
    }


def _client() -> TestClient:
    reports = {
        ("u1", "attachment"): _report("u1", "User One", "2026-06-01T00:00:00Z"),
        ("u2", "attachment"): _report("u2", "User Two", "2026-06-02T00:00:00Z"),
    }
    app = FastAPI()
    app.include_router(report_router.router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        supabase_url="http://fake-supabase",
        supabase_publishable_key="fake-anon-key",
        supabase_secret_key="fake-secret-key",
        MEWI_REPORT_READ_JWT_SECRET=SECRET,
    )
    app.dependency_overrides[get_report_read_service] = lambda: ReportReadService(
        FakeResultStore(reports)
    )
    return TestClient(app, raise_server_exceptions=False)


def _auth(user_id: str, *, admin: bool = False) -> dict[str, str]:
    token = create_report_read_token(user_id, SECRET, admin=admin)
    return {"Authorization": f"Bearer {token}"}


def test_me_report_resolves_user_from_token_subject():
    client = _client()

    resp = client.get("/api/v1/report/me/attachment", headers=_auth("u1"))

    assert resp.status_code == 200
    assert resp.json()["user_id"] == "u1"


def test_normal_token_can_read_explicit_self_report():
    client = _client()

    resp = client.get("/api/v1/report/u1/attachment", headers=_auth("u1"))

    assert resp.status_code == 200
    assert resp.json()["user"]["display_name"] == "User One"


def test_normal_token_cannot_read_another_user_report():
    client = _client()

    resp = client.get("/api/v1/report/u2/attachment", headers=_auth("u1"))

    assert resp.status_code == 403


def test_admin_token_can_read_any_user_report():
    client = _client()

    resp = client.get("/api/v1/report/u2/attachment", headers=_auth("admin", admin=True))

    assert resp.status_code == 200
    assert resp.json()["user_id"] == "u2"


def test_normal_list_returns_only_own_card():
    client = _client()

    resp = client.get("/api/v1/report/?product=attachment", headers=_auth("u1"))

    assert resp.status_code == 200
    data = resp.json()
    assert [item["user_id"] for item in data] == ["u1"]
    assert data[0]["display_name"] == "User One"


def test_admin_list_returns_all_cards_newest_first():
    client = _client()

    resp = client.get("/api/v1/report/?product=attachment", headers=_auth("admin", admin=True))

    assert resp.status_code == 200
    assert [item["user_id"] for item in resp.json()] == ["u2", "u1"]


def test_missing_bearer_token_is_unauthorized():
    client = _client()

    resp = client.get("/api/v1/report/me/attachment")

    assert resp.status_code == 401
