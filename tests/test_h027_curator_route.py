"""H027 owner route previews exact curator operations before queuing approval."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.routers import skill_curator as curator_router
from agents.core.security import token_store

FINGERPRINT = "a" * 64


class FakeOperations:
    def __init__(self):
        self.calls = []

    def read(self, view, filters=None):
        self.calls.append(("read", view, filters))
        return {"ok": True, "view": view, "private_note": "owner-only curator data",
                "filters": filters or {}}

    def preview(self, operation, args):
        self.calls.append(("preview", operation, args))
        return {"ok": True, "status": "preview", "operation": operation,
                "targets": [{"id": "notes"}], "preview_fingerprint": FINGERPRINT}

    def request(self, operation, args, *, preview_fingerprint, actor, authorize):
        self.calls.append(("request", operation, args, preview_fingerprint, actor))
        assert callable(authorize)
        if preview_fingerprint != FINGERPRINT:
            return {"ok": False, "status": "refused", "reason": "stale_preview"}
        return {"ok": True, "status": "pending", "card_id": 7,
                "preview_fingerprint": FINGERPRINT, "targets": [{"id": "notes"}]}


@pytest.fixture
def owner_app(tmp_path, monkeypatch):
    store = token_store.TokenStore(str(tmp_path / "tokens.db"))
    monkeypatch.setattr(token_store, "_store", store)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-token")
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    operations = FakeOperations()
    monkeypatch.setattr(curator_router, "get_orch", lambda: SimpleNamespace(curator_operations=operations))
    app = FastAPI()
    app.include_router(curator_router.router)
    try:
        yield TestClient(app), operations
    finally:
        store.close()


@pytest.mark.parametrize("view", [
    "status", "usage", "list-unmanaged", "list-archived", "ledger", "backups",
])
def test_curator_reads_require_real_admin_and_return_full_private_payload_no_store(owner_app, view):
    client, operations = owner_app
    path = f"/api/curator/{view}"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-User-Token": "user-token"}).status_code == 401
    assert operations.calls == []
    response = client.get(path, headers={"X-Admin-Token": "owner-token"})
    assert response.status_code == 200
    assert response.json()["private_note"] == "owner-only curator data"
    assert "no-store" in response.headers["Cache-Control"]
    assert operations.calls == [("read", view, {})]


def test_preview_is_read_only_and_request_only_queues_exact_owner_card(owner_app):
    client, operations = owner_app
    headers = {"X-Admin-Token": "owner-token"}
    body = {"operation": "pin", "args": {"name": "notes"}}
    preview = client.post("/api/curator/preview", json=body, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["preview_fingerprint"] == FINGERPRINT
    assert "no-store" in preview.headers["Cache-Control"]
    assert operations.calls == [("preview", "pin", {"name": "notes"})]
    request = client.post("/api/curator/request",
                          json={**body, "preview_fingerprint": FINGERPRINT}, headers=headers)
    assert request.status_code == 202
    assert request.json()["status"] == "pending"
    assert request.json()["card_id"] == 7
    assert "no-store" in request.headers["Cache-Control"]
    assert operations.calls[-1] == ("request", "pin", {"name": "notes"}, FINGERPRINT, "owner")


def test_missing_stale_and_tainted_review_never_queue_or_apply(owner_app, monkeypatch):
    client, operations = owner_app
    headers = {"X-Admin-Token": "owner-token"}
    body = {"operation": "archive", "args": {"name": "notes"}}
    missing = client.post("/api/curator/request", json=body, headers=headers)
    assert missing.status_code == 422 and operations.calls == []
    stale = client.post("/api/curator/request",
                        json={**body, "preview_fingerprint": "b" * 64}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["reason"] == "stale_preview"
    assert len(operations.calls) == 1 and operations.calls[0][0] == "request"
    operations.calls.clear()
    monkeypatch.setattr(curator_router, "current_action_origin", lambda: "inbound")
    tainted = client.post("/api/curator/request",
                          json={**body, "preview_fingerprint": FINGERPRINT}, headers=headers)
    assert tainted.status_code == 403 and operations.calls == []
    assert "no-store" in tainted.headers["Cache-Control"]


@pytest.mark.parametrize("body", [
    {"operation": "pin", "args": {"name": "notes", "actor": "owner"}},
    {"operation": "purge", "args": {"days": 0}},
    {"operation": "rollback", "args": {"ledger_id": "one", "backup_id": "two"}},
    {"operation": "adopt", "args": {"name": "notes", "all_unmanaged": True}},
    {"operation": "invalid", "args": {}},
])
def test_invalid_or_authority_claiming_operation_is_rejected_before_core(owner_app, body):
    client, operations = owner_app
    response = client.post("/api/curator/preview", json=body,
                           headers={"X-Admin-Token": "owner-token"})
    assert response.status_code == 422
    assert operations.calls == []


@pytest.mark.parametrize("path", [
    "/api/curator/status?name=notes",
    "/api/curator/usage?limit=1&limit=2",
    "/api/curator/ledger?secret=private",
])
def test_unknown_or_duplicate_read_filters_are_refused_before_core(owner_app, path):
    client, operations = owner_app
    response = client.get(path, headers={"X-Admin-Token": "owner-token"})
    assert response.status_code == 422
    assert "no-store" in response.headers["Cache-Control"]
    assert operations.calls == []


def test_unreadable_core_state_is_a_bounded_error_not_success(owner_app, monkeypatch):
    client, operations = owner_app
    monkeypatch.setattr(operations, "read", lambda *_: {
        "ok": False, "status": "refused", "reason": "state_unavailable",
        "private_exception": "/owner/private/path",
    })
    response = client.get("/api/curator/status", headers={"X-Admin-Token": "owner-token"})
    assert response.status_code == 503
    assert response.json() == {"ok": False, "status": "refused", "reason": "state_unavailable"}
    assert "no-store" in response.headers["Cache-Control"]


def test_rollback_preview_allows_newest_verified_backup_default(owner_app):
    client, operations = owner_app
    response = client.post("/api/curator/preview", json={"operation": "rollback", "args": {}},
                           headers={"X-Admin-Token": "owner-token"})
    assert response.status_code == 200
    assert operations.calls == [("preview", "rollback", {})]
