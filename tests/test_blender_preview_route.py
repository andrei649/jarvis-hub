"""Owner-initiated inspection of a native project, independent of chat dispatch."""

import asyncio
import threading

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.routers import canvas

URL = "/api/canvas/blender-preview"
HEADERS = {"Content-Type": "application/octet-stream"}


@pytest.fixture
def owner_headers(monkeypatch):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "fixture-owner")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "fixture-user")
    return {**HEADERS, "X-Admin-Token": "fixture-owner", "X-User-Token": "fixture-user"}


def test_requires_owner_even_for_invalid_content(monkeypatch):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "fixture-owner")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "fixture-user")
    client = TestClient(web.app)
    for headers in ({}, {"X-User-Token": "fixture-user"}):
        assert client.post(URL, content=b"invalid", headers=headers).status_code in (401, 403)
    owner = {"X-Admin-Token": "fixture-owner", "X-User-Token": "fixture-user"}
    assert client.post(URL, content=b"invalid", headers=owner).status_code == 415


def test_rejects_empty_and_oversized_input_before_starting_blender(monkeypatch, owner_headers):
    from agents.core import blender_preview
    monkeypatch.setattr(blender_preview, "preview_blend", lambda _: pytest.fail("ran Blender"))
    client = TestClient(web.app)
    assert client.post(URL, content=b"", headers=owner_headers).status_code == 422
    assert client.post(URL, content=b"x", headers={
        **owner_headers, "Content-Length": str(blender_preview.MAX_BYTES + 1),
    }).status_code == 413
    monkeypatch.setattr(blender_preview, "MAX_BYTES", 4)
    assert client.post(URL, content=iter([b"abc", b"de"]), headers=owner_headers).status_code == 413


def test_returns_only_inventory_and_static_failure_messages(monkeypatch, owner_headers):
    from agents.core import blender_preview
    inventory = {"kind": "blend", "segments": [{"label": "Objects", "text": "Cube", "truncated": False}], "total_segments": 1}
    monkeypatch.setattr(blender_preview, "preview_blend", lambda _: inventory)
    client = TestClient(web.app)
    response = client.post(URL, content=b"project", headers=owner_headers)
    assert response.status_code == 200 and response.json() == inventory
    assert "no-store" in response.headers["Cache-Control"]
    for error, status in ((blender_preview.BlenderUnavailable, 503), (blender_preview.BlenderPreviewError, 422)):
        def fail(_):
            raise error("private internal filename")
        monkeypatch.setattr(blender_preview, "preview_blend", fail)
        response = client.post(URL, content=b"project", headers=owner_headers)
        assert response.status_code == status and b"private internal" not in response.content


def request():
    async def receive():
        return {"type": "http.request", "body": b"test", "more_body": False}
    return Request({"type": "http", "headers": [(b"content-type", b"application/octet-stream")]}, receive)


@pytest.mark.asyncio
async def test_cancelled_client_does_not_release_live_blender_slot(monkeypatch):
    from agents.core import blender_preview
    entered, finish = threading.Event(), threading.Event()
    gate = threading.BoundedSemaphore(1)
    monkeypatch.setattr(canvas, "_blend_preview_slot", gate)

    def slow(_):
        entered.set()
        finish.wait(5)
        return {}

    monkeypatch.setattr(blender_preview, "preview_blend", slow)
    work = asyncio.create_task(canvas.canvas_blender_preview(request()))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert (await canvas.canvas_blender_preview(request())).status_code == 429
    finally:
        finish.set()
        acquired = await asyncio.to_thread(gate.acquire, True, 3)
        assert acquired
        gate.release()
