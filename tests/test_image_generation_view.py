"""Owner-only, bounded task projection for the image composer."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core.routers import multimodal


def image_task(*, status="done", result=None, kind="toolrpc.image_generate"):
    return SimpleNamespace(id=17, kind=kind, status=status, payload={"tool": "image_generate", "args": {"prompt": "PRIVATE", "_binding": "PRIVATE"}}, result=result)


def success(**overrides):
    return {"status": "ok", "tool": "image_generate", "result": {"ok": True, "kind": "image", "result": {
        "artifact_id": "a" * 32, "bytes": 80, "width": 512, "height": 512,
        "path": "C:/PRIVATE/image.png", "url": "https://evil.invalid/PRIVATE", **overrides,
    }}}


@pytest.fixture
def app(monkeypatch):
    from agents.core.routers import _component
    app = FastAPI()
    app.include_router(multimodal.router)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    monkeypatch.setattr(_component, "get_orch", lambda: multimodal.get_orch())
    return app


@pytest.mark.asyncio
async def test_owner_projection_redacts_payload_paths_urls_and_unrelated_results(app, monkeypatch):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=lambda task_id: image_task(result=success()))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 200
    assert response.json() == {"task_id": 17, "state": "ready", "artifact": {"id": "a" * 32, "bytes": 80, "width": 512, "height": 512}}
    assert "PRIVATE" not in response.text
    assert "url" not in response.json()["artifact"]


@pytest.mark.parametrize("result", [None, [], 12, {"status": "failed", "reason": "submission_unknown", "secret": "PRIVATE"}, success(artifact_id="../secret"), success(bytes=0), success(bytes=True), success(width=999999), success(height=False), {**success(), "status": "failed"}, {**success(), "tool": "different"}, {**success(), "result": {"ok": "true"}}])
@pytest.mark.asyncio
async def test_done_without_valid_success_is_uncertain_not_generated(app, monkeypatch, result):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=lambda task_id: image_task(result=result))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.json() == {"task_id": 17, "state": "uncertain", "artifact": None}


@pytest.mark.parametrize("status,state", [("blocked", "awaiting_approval"), ("proposed", "awaiting_approval"), ("approved", "queued"), ("running", "generating"), ("rejected", "rejected"), ("deferred", "deferred"), ("failed", "uncertain"), ("quarantined", "refused")])
@pytest.mark.asyncio
async def test_exact_queue_states_are_projected_without_inventing_progress(app, monkeypatch, status, state):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=lambda task_id: image_task(status=status))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.json() == {"task_id": 17, "state": state, "artifact": None}


@pytest.mark.asyncio
async def test_projection_requires_admin_and_rejects_non_image_kind_before_serialization(app, monkeypatch):
    calls = []
    def get(task_id):
        calls.append(task_id)
        return image_task(kind="toolrpc.image_generate_evil", result=success())
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=get)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/media/generation-tasks/17")).status_code == 401
        assert calls == []
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
        assert response.status_code == 404
        assert "PRIVATE" not in response.text


@pytest.mark.parametrize("task_id", ["0", "-1", str(2**63), "nonnumeric"])
@pytest.mark.asyncio
async def test_invalid_task_id_never_reaches_durable_store(app, monkeypatch, task_id):
    def forbidden(task_id):
        pytest.fail("invalid ID reached the durable store")
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=forbidden)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get(f"/api/media/generation-tasks/{task_id}", headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 422


@pytest.mark.parametrize("queue", [None, SimpleNamespace(get=lambda task_id: None)])
@pytest.mark.asyncio
async def test_unavailable_queue_and_missing_task_are_explicit(app, monkeypatch, queue):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=queue))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == (503 if queue is None else 404)
    assert response.json() == {"error": "image task state not available" if queue is None else "image task not found"}
