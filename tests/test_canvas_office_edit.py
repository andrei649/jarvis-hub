"""Create an Office export, edit a copy, and reopen both through the canvas API."""

import base64

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.routers._deps import user_guard

EDIT = "/api/canvas/office-edit"


@pytest.mark.parametrize(("kind", "export", "target", "sheet"), [
    ("docx", {"text": "Keep this paragraph.\n\nChange this value."}, "Change this value.", None),
    ("xlsx", {"rows": [["Keep this cell.", "Change this value."]]}, "B1", "Sheet1"),
])
def test_create_edit_and_reopen_office_copies(kind, export, target, sheet):
    client = TestClient(web.app)
    original = client.post("/api/canvas/export", json={"format": kind, **export})
    assert original.status_code == 200
    payload = {"kind": kind, "source_base64": base64.b64encode(original.content).decode("ascii"),
               "target": target, "replacement": "Revised value."}
    if sheet:
        payload["sheet"] = sheet
    revised = client.post(EDIT, json=payload)
    assert revised.status_code == 200
    assert revised.headers["content-type"] == original.headers["content-type"]
    assert "attachment" in revised.headers["content-disposition"]
    assert revised.headers["cache-control"] == "no-store"
    for response, expected, absent in [(original, "Change this value.", "Revised value."),
                                       (revised, "Revised value.", "Change this value.")]:
        preview = client.post("/api/canvas/office-preview", params={"kind": kind}, content=response.content,
                              headers={"Content-Type": "application/octet-stream"})
        assert preview.status_code == 200
        text = preview.json()["segments"][0]["text"]
        assert "Keep this" in text and expected in text and absent not in text


def test_office_edit_refuses_unbounded_invalid_and_unauthorized_requests(monkeypatch):
    client = TestClient(web.app)
    assert client.post(EDIT, content=b"raw").status_code == 415
    assert client.post(EDIT, json={}, headers={"Content-Length": str(12 * 1024 * 1024)}).status_code == 413
    data = {"kind": "docx", "target": "Private phrase", "replacement": "Revised", "source_base64": "invalid!"}
    refused = client.post(EDIT, json=data)
    assert refused.status_code == 422 and "Private phrase" not in refused.text
    monkeypatch.delitem(web.app.dependency_overrides, user_guard, raising=False)
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    remote = TestClient(web.app, client=("203.0.113.9", 50000))
    assert remote.post(EDIT, json=data).status_code in (401, 403)
