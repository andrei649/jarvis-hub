"""Owner-only bounded native Blender download route."""

import asyncio
import threading

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import blender_export, blender_preview
from agents.core.routers import canvas


URL = "/api/canvas/blender-export"
OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


@pytest.fixture
def owner_headers(monkeypatch):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "fixture-owner")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "fixture-user")
    return {"X-Admin-Token": "fixture-owner", "X-User-Token": "fixture-user",
            "Content-Type": "text/plain; charset=utf-8"}


def test_guard_content_type_and_bounded_input(monkeypatch, owner_headers):
    client = TestClient(web.app)
    assert client.post(URL, content=OBJ, headers={"Content-Type": "text/plain"}).status_code in (401, 403)
    assert client.post(URL, content=OBJ, headers={**owner_headers, "Content-Type": "application/json"}).status_code == 415
    assert client.post(URL, content=b"", headers=owner_headers).status_code == 422
    assert client.post(URL, content=OBJ, headers={**owner_headers,
        "Content-Length": str(blender_export.MAX_BYTES + 1)}).status_code == 413
    assert client.post(URL, content=b"mtllib secret.mtl", headers=owner_headers).status_code == 422


def test_download_and_fixed_failures(monkeypatch, owner_headers):
    client = TestClient(web.app)
    monkeypatch.setattr(blender_export, "export_obj", lambda _: b"BLENDER-native")
    response = client.post(URL, content=OBJ, headers=owner_headers)
    assert response.status_code == 200 and response.content == b"BLENDER-native"
    assert response.headers["content-type"] == "application/x-blender"
    assert response.headers["content-disposition"] == 'attachment; filename="Nerva model.blend"'
    assert response.headers["cache-control"] == "no-store"
    for error, status in ((blender_preview.BlenderUnavailable, 503),
                          (blender_export.BlenderBuildError, 503)):
        def fail(_):
            raise error("private path C:/secret")
        monkeypatch.setattr(blender_export, "export_obj", fail)
        response = client.post(URL, content=OBJ, headers=owner_headers)
        assert response.status_code == status and b"C:/secret" not in response.content
    monkeypatch.setattr(blender_export, "export_obj", lambda _: (_ for _ in ()).throw(
        blender_export.BlenderExportError("Unsupported OBJ directive")))
    assert client.post(URL, content=OBJ, headers=owner_headers).json()["error"] == "Unsupported OBJ directive"


def request(content_type=b"text/plain"):
    async def receive():
        return {"type": "http.request", "body": OBJ, "more_body": False}
    return Request({"type": "http", "headers": [(b"content-type", content_type)]}, receive)


@pytest.mark.asyncio
async def test_cancelled_client_keeps_shared_blender_slot_until_worker_finishes(monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    slot = threading.BoundedSemaphore(1)
    monkeypatch.setattr(canvas, "_blend_preview_slot", slot)

    def slow(_):
        entered.set()
        finish.wait(5)
        return b"BLENDER-native"

    monkeypatch.setattr(blender_export, "export_obj", slow)
    task = asyncio.create_task(canvas.canvas_blender_export(request()))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await canvas.canvas_blender_export(request())).status_code == 429
        assert (await canvas.canvas_blender_preview(request(b"application/octet-stream"))).status_code == 429
    finally:
        finish.set()
        assert await asyncio.to_thread(slot.acquire, True, 3)
        slot.release()
