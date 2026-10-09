"""DeepInfra catalog refresh and image generation through real signed tasks."""

import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_tool import tool  # noqa: F401

MODEL = "black-forest-labs/FLUX-1-schnell"
CATALOG = {"data": [
    {"id": "vendor/chat", "metadata": {"tags": ["chat"]}},
    {"id": MODEL, "metadata": {"tags": ["image-gen"], "default_width": 1024}},
]}


@pytest.fixture
def provider(cloud, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-deepinfra"], "enabled", True)
    cloud.runtime.deepinfra_key = lambda: cloud.state.key
    return cloud


async def refresh(provider, *, catalog=CATALOG):
    provider.state.response = lambda: httpx.Response(200, json=catalog)
    task_id = provider.runtime.refresh_catalog("deepinfra", "user")
    assert not provider.requests
    task = provider.queue.get(task_id)
    assert task.kind == "plugin.egress" and task.payload["plugin"] == "cloud-image-deepinfra"
    assert task.payload["image"]["body"] == {"operation": "catalog_refresh", "prompt": ""}
    await provider.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await provider.worker.tick()
    return provider.queue.get(task_id)


def test_deepinfra_discovery_default_off_and_cold_status_does_not_dial(cloud):
    from agents.core.plugin_gate import BUILTIN_PLUGINS, NetworkAccess

    manifest = BUILTIN_PLUGINS["cloud-image-deepinfra"]
    assert manifest.enabled is False
    assert manifest.network_access is NetworkAccess.RESTRICTED
    assert manifest.allowed_domains == ["api.deepinfra.com"]
    cloud.runtime.deepinfra_key = lambda: pytest.fail("disabled provider read credential")
    status = cloud.runtime.status()["providers"]["deepinfra"]
    assert status["enabled"] is False and status["configured"] is False
    assert status["models"] == [] and status["default_model"] == ""
    assert not cloud.requests


@pytest.mark.asyncio
async def test_catalog_refresh_is_one_approved_get_with_tag_filter_and_durable_snapshot(provider):
    from agents.core.media_backends.deepinfra_image import CATALOG_ENDPOINT

    before = provider.runtime.status()["providers"]["deepinfra"]
    assert before["enabled"] is True and before["configured"] is False
    assert before["catalog_refresh_available"] is True
    assert before["models"] == [] and before["default_model"] == ""
    task = await refresh(provider)
    assert task.result["status"] == "ok", task.result
    assert len(provider.requests) == 1 and provider.requests[0].method == "GET"
    assert task.payload["url"] == CATALOG_ENDPOINT
    assert provider.requests[0].url.path == "/v1/openai/models"
    assert provider.requests[0].url.query == b"filter=true&sort_by=hermes"
    assert provider.requests[0].headers["host"] == "api.deepinfra.com"
    assert provider.requests[0].headers["authorization"] == "Bearer fixture-credential"
    record = json.loads((provider.runtime.records / "deepinfra-models.json").read_text())
    assert record["task_id"] == task.id and record["binding"]
    assert list(record["catalog"]) == [MODEL]
    status = provider.runtime.status()["providers"]["deepinfra"]
    assert status["configured"] is True
    assert status["models"] == [MODEL] and status["default_model"] == MODEL
    assert status["model_capabilities"][MODEL]["max_reference_images"] == 0
    assert (await provider.runtime.execute(task))["status"] == "refused"
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_invalid_catalog_cannot_become_available_or_trigger_image_post(provider):
    task = await refresh(provider, catalog={"data": {"id": MODEL}})
    assert task.result["status"] != "ok", task.result
    assert [request.method for request in provider.requests] == ["GET"]
    assert provider.runtime.status()["providers"]["deepinfra"]["models"] == []
    with pytest.raises(ValueError):
        provider.runtime.submit("blue square", {"backend": "deepinfra", "model": MODEL}, "user")
    assert [request.method for request in provider.requests] == ["GET"]


@pytest.mark.asyncio
async def test_selected_model_single_post_publishes_local_png_and_never_replays(provider):
    from agents.core.media_backends.comfyui import artifact_bytes

    await refresh(provider)
    provider.requests.clear()
    encoded = base64.b64encode(png((640, 512))).decode()
    provider.state.response = lambda: httpx.Response(200, json={"data": [{"b64_json": encoded}]})
    task_id = provider.runtime.submit("blue square", {
        "backend": "deepinfra", "model": MODEL, "size": "1024x1024"}, "user")
    task = provider.queue.get(task_id)
    assert task.payload["image"]["catalog_digest"]
    assert not provider.requests
    await provider.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await provider.worker.tick()
    task = provider.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    assert [request.method for request in provider.requests] == ["POST"]
    assert provider.requests[0].url.path == "/v1/openai/images/generations"
    assert json.loads(provider.requests[0].content) == {
        "model": MODEL, "prompt": "blue square", "size": "1024x1024", "n": 1}
    artifact = task.result["result"]["result"]
    assert (artifact["width"], artifact["height"]) == (640, 512)
    assert artifact_bytes(artifact["artifact_id"], provider.root / "media" / "generated")
    assert (await provider.runtime.execute(task))["status"] == "refused"
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_changed_catalog_snapshot_refuses_queued_model_without_post(provider):
    await refresh(provider)
    task_id = provider.runtime.submit("blue square", {"backend": "deepinfra", "model": MODEL}, "user")
    provider.requests.clear()
    await refresh(provider, catalog={"data": [{"id": "vendor/new-image", "metadata": {"tags": ["image-gen"]}}]})
    provider.requests.clear()
    await provider.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await provider.worker.tick()
    refused = provider.queue.get(task_id)
    assert refused.status == "failed" and refused.result.get("status") != "ok"
    assert not provider.requests


@pytest.mark.asyncio
async def test_ambiguous_deepinfra_post_is_not_retried(provider):
    await refresh(provider)
    provider.requests.clear()

    def lost():
        raise httpx.ReadError("provider private details")

    provider.state.response = lost
    task_id = provider.runtime.submit("blue square", {"backend": "deepinfra", "model": MODEL}, "user")
    await provider.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await provider.worker.tick()
    task = provider.queue.get(task_id)
    assert task.result["status"] == "unknown", task.result
    assert (await provider.runtime.execute(task))["status"] == "refused"
    assert [request.method for request in provider.requests] == ["POST"]
    assert "provider private details" not in str(task.result)


@pytest.mark.asyncio
async def test_registered_tool_proposes_deepinfra_with_actor_after_catalog_refresh(provider, tool):
    await refresh(provider)
    provider.requests.clear()
    result = await tool.server.handle({"tool": "image_generate", "args": {
        "cloud": True, "backend": "deepinfra", "model": MODEL,
        "prompt": "blue square", "size": "1024x1024",
    }}, actor="athena")
    assert result["reason"] == "approval_required", result
    task = provider.queue.get(result["task_id"])
    assert task.agent == "athena" and task.kind == "plugin.egress"
    assert task.payload["plugin"] == "cloud-image-deepinfra"
    assert not provider.requests


def test_route_proposes_explicit_deepinfra_catalog_refresh_without_network(provider, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=provider.runtime))
    response = TestClient(web.app).post("/api/media/generate", headers={"X-User-Token": "user-token"},
        json={"kind": "image", "cloud": True, "backend": "deepinfra",
              "prompt": "", "refresh_catalog": True})
    assert response.status_code == 202, response.text
    task = provider.queue.get(response.json()["task_id"])
    assert task.payload["image"]["body"]["operation"] == "catalog_refresh"
    assert not provider.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["model", "approver", "credential"])
async def test_catalog_snapshot_or_authority_change_requires_new_refresh(provider, change):
    task = await refresh(provider)
    provider.requests.clear()
    if change == "model":
        path = provider.runtime.records / "deepinfra-models.json"
        record = json.loads(path.read_text())
        record["catalog"]["vendor/forged-image"] = {}
        path.write_text(json.dumps(record))
    elif change == "approver":
        provider.queue._conn.execute("UPDATE tasks SET decided_by='another owner' WHERE id=?", (task.id,))
        provider.queue._conn.commit()
    else:
        provider.state.key = "rotated credential"
    assert provider.runtime.status()["providers"]["deepinfra"]["configured"] is False
    with pytest.raises(ValueError):
        provider.runtime.submit("blue square", {"backend": "deepinfra", "model": MODEL}, "user")
    assert not provider.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("withdraw", ["credential", "manifest", "estop"])
async def test_catalog_response_does_not_persist_after_authority_withdrawal(provider, monkeypatch, withdraw):
    from agents.core import estop
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    def response():
        if withdraw == "credential":
            provider.state.key = "rotated credential"
        elif withdraw == "manifest":
            monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-deepinfra"], "enabled", False)
        else:
            monkeypatch.setattr(estop, "is_engaged", lambda: True)
        return httpx.Response(200, json=CATALOG)

    provider.state.response = response
    task_id = provider.runtime.refresh_catalog("deepinfra", "user")
    await provider.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await provider.worker.tick()
    assert provider.queue.get(task_id).result["status"] == "refused"
    assert [request.method for request in provider.requests] == ["GET"]
    assert not (provider.runtime.records / "deepinfra-models.json").exists()


@pytest.mark.parametrize("operation", [
    {"cloud": False, "backend": "deepinfra", "refresh_catalog": True, "prompt": ""},
    {"cloud": True, "backend": "deepinfra", "refresh_catalog": False, "prompt": ""},
    {"cloud": True, "backend": "deepinfra", "refresh_catalog": True, "prompt": "generate"},
    {"cloud": True, "backend": "deepinfra", "refresh_catalog": True, "prompt": "", "model": MODEL},
    {"cloud": True, "backend": "krea", "resume_task_id": True, "prompt": ""},
    {"cloud": True, "backend": "krea", "resume_task_id": 1, "refresh_catalog": True, "prompt": ""},
])
def test_special_operation_forms_refuse_before_enqueue(provider, monkeypatch, operation):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=provider.runtime))
    response = TestClient(web.app).post("/api/media/generate", headers={"X-User-Token": "user-token"},
        json={"kind": "image", **operation})
    assert response.status_code == 422
    assert not provider.requests and not provider.queue.list()
