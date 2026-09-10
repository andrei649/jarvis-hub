"""Composer contract through production composition; only ComfyUI is simulated."""

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core.routers import _component, autonomy, multimodal
from tests.test_image_mediation_composition import composed as composed
from tests.test_local_image_runtime import PNG


@pytest.mark.asyncio
async def test_composer_observes_one_approved_image_and_can_resume_reads(composed, monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "image-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "image-owner")
    for module in (_component, autonomy, multimodal):
        monkeypatch.setattr(module, "get_orch", lambda: composed.orch)
    app = FastAPI()
    app.include_router(multimodal.router)
    app.include_router(autonomy.router)
    owner = {"X-User-Token": "image-user", "X-Admin-Token": "image-owner"}
    prompt = "O barcă albastră pe lac"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        proposal = await client.post("/api/media/generate", headers=owner,
                                     json={"kind": "image", "prompt": prompt, "cloud": False})
        assert proposal.status_code == 202, proposal.text
        task_id = proposal.json()["task_id"]
        path = f"/api/media/generation-tasks/{task_id}"
        assert (await client.get(path, headers={"X-User-Token": "image-user"})).status_code == 401
        pending = await client.get(path, headers=owner)
        assert pending.json() == {"task_id": task_id, "state": "awaiting_approval", "artifact": None}
        await composed.worker.tick()
        assert composed.requests == []

        decision = await client.post(f"/autonomy/tasks/{task_id}/decision", headers=owner,
                                    json={"action": "accept"})
        assert decision.status_code == 200, decision.text
        assert composed.requests == []
        await composed.worker.tick()
        ready = await client.get(path, headers=owner)
        assert ready.status_code == 200
        value = ready.json()
        assert value["task_id"] == task_id and value["state"] == "ready", value
        assert value["artifact"]["bytes"] == len(PNG)
        assert prompt not in ready.text and "_binding" not in ready.text
        assert "url" not in value["artifact"] and "path" not in value["artifact"]
        artifact_path = "/api/media/generated/" + value["artifact"]["id"]
        assert (await client.get(artifact_path)).status_code == 401
        png = await client.get(artifact_path, headers=owner)
        assert png.content == PNG and png.headers["content-type"] == "image/png"
        assert png.headers["cache-control"] == "no-store"
        assert png.headers["x-content-type-options"] == "nosniff"

        # A reload/resume observes the same result; it creates no new proposal or effect.
        assert (await client.get(path, headers=owner)).json() == value
        assert (await client.get(artifact_path, headers=owner)).content == PNG
        await composed.worker.tick()
        assert sum(request.method == "POST" for request in composed.requests) == 1


@pytest.mark.asyncio
async def test_composer_edits_the_artifact_it_just_generated_over_http(composed, monkeypatch):
    """The whole H515/H598 circuit end to end: generate, then feed that result's own
    opaque id back in as the reference for an edit.

    The point of the round trip is that the HUD never needs — and never gets — a path.
    The id the download route serves is the same id the edit route accepts, and the
    edit produces a *second* artifact, leaving the first one intact.
    """
    monkeypatch.setattr(web, "USER_TOKEN", "image-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "image-owner")
    for module in (_component, autonomy, multimodal):
        monkeypatch.setattr(module, "get_orch", lambda: composed.orch)
    app = FastAPI()
    app.include_router(multimodal.router)
    app.include_router(autonomy.router)
    owner = {"X-User-Token": "image-user", "X-Admin-Token": "image-owner"}

    async def approved(client, body):
        proposal = await client.post("/api/media/generate", headers=owner, json=body)
        assert proposal.status_code == 202, proposal.text
        task_id = proposal.json()["task_id"]
        decision = await client.post(f"/autonomy/tasks/{task_id}/decision", headers=owner,
                                     json={"action": "accept"})
        assert decision.status_code == 200, decision.text
        await composed.worker.tick()
        state = (await client.get(f"/api/media/generation-tasks/{task_id}", headers=owner)).json()
        assert state["state"] == "ready", state
        return state["artifact"]["id"]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/media", headers=owner)).json()["local_image"]["edit"] is True
        original = await approved(client, {"kind": "image", "prompt": "o barcă albastră", "cloud": False})
        edited = await approved(client, {"kind": "image", "prompt": "acum ninge", "cloud": False,
                                         "reference": original, "strength": 40})
        assert edited != original
        for artifact_id in (original, edited):
            png = await client.get("/api/media/generated/" + artifact_id, headers=owner)
            assert png.status_code == 200 and png.content == PNG

        # Both edits and generations went through the queue; nothing rode along on the
        # first approval. Two tuples, two uploads-or-not, two prompt submissions.
        submissions = [r.url.path for r in composed.requests if r.method == "POST"]
        assert submissions == ["/prompt", "/upload/image", "/prompt"]

        # A reference the hub never minted is refused by the body schema, before any
        # task exists to approve.
        for reference in ("../../etc/passwd", "/tmp/x.png", "A" * 32, "a" * 31):
            refused = await client.post("/api/media/generate", headers=owner, json={
                "kind": "image", "prompt": "acum ninge", "cloud": False, "reference": reference})
            assert refused.status_code == 422, reference
        sized = await client.post("/api/media/generate", headers=owner, json={
            "kind": "image", "prompt": "acum ninge", "cloud": False,
            "reference": original, "width": 768})
        assert sized.status_code == 422, sized.text
        assert [r.url.path for r in composed.requests if r.method == "POST"] == submissions
