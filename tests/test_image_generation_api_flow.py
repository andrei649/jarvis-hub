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
