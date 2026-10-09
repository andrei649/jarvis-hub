"""xAI image generation and editing through signed cloud tasks and synthetic HTTP."""

import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_tool import tool  # noqa: F401


@pytest.fixture
def xai(cloud, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-xai"], "enabled", True)
    cloud.runtime.xai_key = lambda: cloud.state.key
    return cloud


def test_xai_default_off_status_has_catalog_without_secret_read_or_http(cloud):
    from agents.core.plugin_gate import BUILTIN_PLUGINS, NetworkAccess

    manifest = BUILTIN_PLUGINS["cloud-image-xai"]
    assert manifest.enabled is False
    assert manifest.network_access is NetworkAccess.RESTRICTED
    assert manifest.allowed_domains == ["api.x.ai", "imgen.x.ai"]
    cloud.runtime.xai_key = lambda: pytest.fail("disabled xAI read credential")
    status = cloud.runtime.status()["providers"]["xai"]
    assert status["enabled"] is False and status["configured"] is False
    assert status["default_model"] == "grok-imagine-image"
    assert set(status["models"]) == {
        "grok-imagine-image", "grok-imagine-image-2.0", "grok-imagine-image-quality"}
    assert not cloud.requests


@pytest.mark.asyncio
async def test_route_selected_xai_2_0_one_post_native_json_and_clean_local_artifact(xai, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.media_backends.comfyui import artifact_bytes

    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=xai.runtime))
    encoded = base64.b64encode(png((640, 512))).decode()
    xai.state.response = lambda: httpx.Response(200, json={"data": [{"b64_json": encoded, "mime_type": "image/png"}]})
    response = TestClient(web.app).post("/api/media/generate", headers={"X-User-Token": "user-token"},
        json={"kind": "image", "cloud": True, "backend": "xai", "prompt": "blue square",
              "model": "grok-imagine-image-2.0", "size": "1024x1536", "resolution": "2k", "quality": "medium"})
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    task = xai.queue.get(task_id)
    assert task.kind == "plugin.egress" and task.payload["plugin"] == "cloud-image-xai"
    assert task.payload["url"] == "https://api.x.ai/v1/images/generations"
    assert not xai.requests
    await xai.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await xai.worker.tick()
    task = xai.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    assert [request.method for request in xai.requests] == ["POST"]
    assert xai.requests[0].headers["host"] == "api.x.ai"
    assert xai.requests[0].headers["authorization"] == "Bearer fixture-credential"
    assert json.loads(xai.requests[0].content) == {
        "model": "grok-imagine-image-2.0", "prompt": "blue square",
        "aspect_ratio": "9:16", "resolution": "2k", "quality": "medium",
        "response_format": "b64_json", "n": 1,
    }
    artifact = task.result["result"]["result"]
    assert (artifact["width"], artifact["height"]) == (640, 512)
    data = artifact_bytes(artifact["artifact_id"], xai.root / "media" / "generated")
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "PNG" and image.size == (640, 512)
        assert not image.info
    assert task.result["result"]["catalog_id"]


@pytest.mark.asyncio
async def test_registered_xai_tool_only_proposes_signed_actor_task(xai, tool):
    response = await tool.server.handle({"tool": "image_generate", "args": {
        "cloud": True, "backend": "xai", "model": "grok-imagine-image",
        "prompt": "blue square", "size": "1024x1024",
    }}, actor="athena")
    assert response["reason"] == "approval_required", response
    task = xai.queue.get(response["task_id"])
    assert task.agent == "athena" and task.kind == "plugin.egress"
    assert task.payload["plugin"] == "cloud-image-xai"
    assert not xai.requests


@pytest.mark.asyncio
async def test_xai_edit_uploads_owned_png_and_refuses_changed_reference_before_post(xai):
    reference_id = "a" * 32
    directory = xai.root / "media" / "generated"
    directory.mkdir(parents=True)
    first = png((512, 512))
    (directory / (reference_id + ".png")).write_bytes(first)
    encoded = base64.b64encode(png((640, 512))).decode()
    xai.state.response = lambda: httpx.Response(200, json={"data": [{"b64_json": encoded}]})
    options = {"backend": "xai", "model": "grok-imagine-image-2.0", "references": [reference_id]}
    task_id = xai.runtime.submit("make a variation", options, "user")
    task = xai.queue.get(task_id)
    assert task.payload["image"]["body"]["reference_digests"]
    assert task.payload["url"] == "https://api.x.ai/v1/images/edits"
    await xai.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await xai.worker.tick()
    assert xai.queue.get(task_id).result["status"] == "ok"
    wire = json.loads(xai.requests[0].content)
    assert wire["model"] == "grok-imagine-image-2.0"
    assert wire["image"] == {"type": "image_url", "url": "data:image/png;base64," + base64.b64encode(first).decode()}
    assert len(xai.requests) == 1

    xai.requests.clear()
    task_id = xai.runtime.submit("make a variation", options, "user")
    await xai.worker.apply_decision(task_id, "accept", decided_by="test owner")
    (directory / (reference_id + ".png")).write_bytes(png((768, 512)))
    await xai.worker.tick()
    refused = xai.queue.get(task_id)
    assert refused.status == "failed" and refused.result.get("status") != "ok"
    assert not xai.requests


@pytest.mark.asyncio
async def test_xai_url_result_download_is_credential_free_and_egress_admitted(xai, monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    xai.state.response = iter((
        httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/xai-imgen/result.png"}]}),
        httpx.Response(200, content=png((640, 512))),
    )).__next__
    task_id = xai.runtime.submit("blue square", {"backend": "xai"}, "user")
    await xai.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await xai.worker.tick()
    assert xai.queue.get(task_id).result["status"] == "ok"
    assert [request.method for request in xai.requests] == ["POST", "GET"]
    assert xai.requests[1].headers["host"] == "imgen.x.ai"
    assert "authorization" not in xai.requests[1].headers

    xai.requests.clear()
    xai.state.response = lambda: httpx.Response(200, json={"data": [{"url": "https://unadmitted.example/result.png"}]})
    task_id = xai.runtime.submit("blue square", {"backend": "xai"}, "user")
    await xai.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await xai.worker.tick()
    assert xai.queue.get(task_id).result["status"] != "ok"
    assert [request.method for request in xai.requests] == ["POST"]


@pytest.mark.asyncio
async def test_xai_ambiguous_post_never_replays(xai):
    def lost():
        raise httpx.ReadError("private provider details")

    xai.state.response = lost
    task_id = xai.runtime.submit("blue square", {"backend": "xai"}, "user")
    await xai.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await xai.worker.tick()
    task = xai.queue.get(task_id)
    assert task.result["status"] == "unknown", task.result
    assert (await xai.runtime.execute(task))["status"] == "refused"
    assert [request.method for request in xai.requests] == ["POST"]
    assert "private provider details" not in str(task.result)


def test_xai_model_specific_quality_resolution_restrictions_apply_at_submit(xai):
    for options in (
        {"model": "grok-imagine-image", "quality": "low"},
        {"model": "grok-imagine-image-2.0", "quality": "high"},
        {"model": "grok-imagine-image-2.0", "resolution": "4k"},
        {"model": "grok-imagine-image-2.0", "references": ["a" * 32], "resolution": "2k"},
    ):
        with pytest.raises(ValueError):
            xai.runtime.submit("blue square", {"backend": "xai", **options}, "user")
    assert not xai.requests
