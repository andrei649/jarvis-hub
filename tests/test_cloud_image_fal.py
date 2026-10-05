"""FAL images use the same signed cloud task and local artifact path."""

import json

import httpx
import pytest

from tests.test_cloud_image import cloud, png  # noqa: F401: shared mediated worker fixture


@pytest.fixture
def fal(cloud, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-fal"], "enabled", True)
    cloud.runtime.fal_key = lambda: cloud.state.key
    return cloud


@pytest.mark.asyncio
async def test_fal_route_worker_download_and_catalog_publish(fal, monkeypatch):
    """Removing FAL dispatch or using OpenAI's fixed-size decoder breaks this flow."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.media_backends.comfyui import artifact_bytes

    fal.state.response = iter((
        httpx.Response(200, json={"images": [{"url": "https://v3.fal.media/files/result.png"}]}),
        httpx.Response(200, content=png((640, 512))),
    )).__next__
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=fal.runtime))
    client = TestClient(web.app)
    proposal = client.post(
        "/api/media/generate", headers={"X-User-Token": "user-token"},
        json={"kind": "image", "cloud": True, "backend": "fal", "prompt": "blue square",
              "model": "fal-ai/flux-2/klein/9b", "size": "1024x1024"},
    )
    assert proposal.status_code == 202, proposal.text
    task_id = proposal.json()["task_id"]
    task = fal.queue.get(task_id)
    assert task.payload["plugin"] == "cloud-image-fal"
    assert task.payload["url"] == "https://fal.run/fal-ai/flux-2/klein/9b"
    assert not fal.requests
    await fal.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await fal.worker.tick()
    result = fal.queue.get(task_id).result
    assert result["status"] == "ok", result
    assert len(fal.requests) == 2
    assert [r.method for r in fal.requests] == ["POST", "GET"]
    assert fal.requests[0].headers["authorization"] == "Key fixture-credential"
    assert fal.requests[0].headers["x-fal-no-retry"] == "1"
    assert "authorization" not in fal.requests[1].headers
    assert json.loads(fal.requests[0].content) == {
        "prompt": "blue square", "image_size": "square_hd", "num_inference_steps": 4,
        "output_format": "png", "enable_safety_checker": False,
    }
    artifact = result["result"]["result"]
    assert (artifact["width"], artifact["height"]) == (640, 512)
    assert artifact_bytes(artifact["artifact_id"], fal.root / "media" / "generated")
    assert fal.runtime.recover(fal.queue.get(task_id))["status"] == "ok"
    assert len(fal.requests) == 2


@pytest.mark.asyncio
async def test_fal_ambiguous_post_is_never_replayed(fal):
    def lost():
        raise httpx.ReadError("network lost")

    fal.state.response = lost
    task_id = fal.runtime.submit("prompt", {"backend": "fal"}, "user")
    await fal.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await fal.worker.tick()
    task = fal.queue.get(task_id)
    assert task.result["status"] == "unknown"
    assert len(fal.requests) == 1
    assert (await fal.runtime.execute(task))["status"] == "refused"
    assert len(fal.requests) == 1


@pytest.mark.asyncio
async def test_fal_credential_rotation_and_provider_mismatch_prevent_dial(fal):
    task_id = fal.runtime.submit("prompt", {"backend": "fal"}, "user")
    fal.state.key = "rotated"
    await fal.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await fal.worker.tick()
    assert not fal.requests

    fal.state.key = "fixture-credential"
    second = fal.runtime.submit("prompt", {"backend": "fal"}, "user")
    await fal.worker.apply_decision(second, "accept", decided_by="test owner")
    task = fal.queue.get(second)
    task.payload["plugin"] = "cloud-image"
    assert fal.runtime.guard(task) is False
    assert not fal.requests


def test_fal_missing_credential_or_disabled_manifest_creates_no_task(cloud, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    cloud.runtime.fal_key = lambda: "fixture-credential"
    with pytest.raises(ValueError):
        cloud.runtime.submit("prompt", {"backend": "fal"}, "user")
    monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-fal"], "enabled", True)
    cloud.runtime.fal_key = lambda: ""
    with pytest.raises(ValueError):
        cloud.runtime.submit("prompt", {"backend": "fal"}, "user")
    assert cloud.queue.list() == [] and cloud.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response,download", [
    (httpx.Response(200, json={"images": []}), None),
    (httpx.Response(200, json={"images": [{"url": "https://fal.media/out.png"}]}),
     httpx.Response(302, headers={"location": "https://other.example/out.png"})),
    (httpx.Response(200, json={"images": [{"url": "https://fal.media/out.png"}]}),
     httpx.Response(200, content=b"invalid raster")),
])
async def test_fal_malformed_result_or_download_redirect_never_publishes(
    fal, response, download,
):
    replies = [response]
    if download is not None:
        replies.append(download)
    fal.state.response = iter(replies).__next__
    task_id = fal.runtime.submit("prompt", {"backend": "fal"}, "user")
    await fal.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await fal.worker.tick()
    task = fal.queue.get(task_id)
    assert task.result["status"] == "failed"
    assert len(fal.requests) == len(replies)
    assert not list((fal.root / "media" / "generated").glob("*.png"))


def test_fal_discovery_does_not_dial(fal):
    status = fal.runtime.status()
    assert status["providers"]["fal"]["configured"] is True
    assert "fal-ai/flux-2/klein/9b" in status["providers"]["fal"]["models"]
    assert status["providers"]["fal"]["reachable"] is None
    assert fal.requests == []


def test_media_kind_reflects_fal_when_openai_unconfigured(fal, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import image_generation_runtime

    fal.runtime.key = lambda: ""
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=fal.runtime))
    monkeypatch.setattr(image_generation_runtime, "configuration_status", lambda: {"configured": False})
    response = TestClient(web.app).get("/api/media", headers={"X-User-Token": "user-token"})
    assert response.status_code == 200
    assert response.json()["cloud_image"]["providers"]["fal"]["configured"] is True
    assert response.json()["kinds"]["image"] is True


def test_route_admits_catalog_edit_limit_without_expanding_local_limit(fal, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=fal.runtime))
    client = TestClient(web.app)
    refs = [f"https://fal.media/files/ref{i}.png" for i in range(17)]
    body = {"kind": "image", "cloud": True, "backend": "fal", "prompt": "edit",
            "model": "fal-ai/gpt-image-1.5"}
    accepted = client.post("/api/media/generate", headers={"X-User-Token": "user-token"},
                           json={**body, "references": refs[:16]})
    assert accepted.status_code == 202, accepted.text
    assert fal.queue.get(accepted.json()["task_id"]).payload["image"]["body"]["references"] == refs[:16]
    too_many = client.post("/api/media/generate", headers={"X-User-Token": "user-token"},
                           json={**body, "references": refs})
    assert too_many.status_code == 422
    local = client.post("/api/media/generate", headers={"X-User-Token": "user-token"},
                        json={"kind": "image", "prompt": "edit", "references": refs[:5]})
    assert local.status_code == 422
    assert fal.requests == []


@pytest.mark.asyncio
async def test_coordinator_dispatches_fal_approval_through_same_worker(fal, monkeypatch):
    from types import SimpleNamespace

    from agents.core import cloud_image_runtime
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    executor = TaskExecutor()
    monkeypatch.setattr(cloud_image_runtime, "CloudImageRuntime", lambda *a, **k: fal.runtime)
    AutonomyCoordinator(SimpleNamespace(
        autonomy=fal.worker, secret_broker=SimpleNamespace(redact=lambda x: x),
    ))._wire_cloud_image(executor)
    fal.worker.executor = executor.execute
    fal.state.response = iter((
        httpx.Response(200, json={"images": [{"url": "https://fal.media/out.png"}]}),
        httpx.Response(200, content=png((512, 512))),
    )).__next__
    task_id = fal.runtime.submit("prompt", {"backend": "fal"}, "user")
    await fal.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await fal.worker.tick()
    assert fal.queue.get(task_id).result["status"] == "ok"
    assert [request.method for request in fal.requests] == ["POST", "GET"]
