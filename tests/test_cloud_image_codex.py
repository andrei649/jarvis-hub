"""Image2 and Codex proposals enter the existing signed one-attempt worker."""

import base64
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from tests.test_cloud_image import cloud, png  # noqa: F401


def _token(account="acct-test", expiry=None):
    claims = {"exp": expiry or int(time.time()) + 3600,
              "https://api.openai.com/auth": {"chatgpt_account_id": account}}
    middle = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "header." + middle + ".signature"


@pytest.fixture
def codex(cloud, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-codex"], "enabled", True)
    source = SimpleNamespace(token=_token(), base="https://chatgpt.com/backend-api/codex")
    cloud.runtime.codex_source = lambda: {"access_token": source.token, "base_url": source.base}
    cloud.source = source
    return cloud


@pytest.mark.asyncio
async def test_actual_codex_route_approved_worker_and_artifact(codex, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.media_backends.comfyui import artifact_bytes

    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=codex.runtime))
    client = TestClient(web.app)
    proposal = client.post("/api/media/generate", headers={"X-User-Token": "user-token"},
                           json={"kind": "image", "cloud": True, "backend": "openai-codex",
                                 "model": "gpt-image-2-high", "prompt": "blue square"})
    assert proposal.status_code == 202, proposal.text
    task_id = proposal.json()["task_id"]
    assert codex.queue.get(task_id).payload["plugin"] == "cloud-image-codex"
    assert codex.requests == []
    await codex.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await codex.worker.tick()
    result = codex.queue.get(task_id).result
    assert result["status"] == "ok", result
    assert len(codex.requests) == 1
    req = codex.requests[0]
    assert req.url.path == "/backend-api/codex/images/generations"
    assert req.headers["host"] == "chatgpt.com"
    assert req.headers["authorization"] == "Bearer " + codex.source.token
    assert req.headers["chatgpt-account-id"] == "acct-test"
    assert json.loads(req.content) == {"model": "gpt-image-2", "prompt": "blue square",
                                       "n": 1, "quality": "high", "size": "1024x1024",
                                       "background": "opaque"}
    artifact = result["result"]["result"]
    assert artifact_bytes(artifact["artifact_id"], codex.root / "media" / "generated")
    assert codex.source.token not in str(result) + str(codex.queue.get(task_id).payload)


@pytest.mark.asyncio
async def test_codex_edit_binds_saved_artifact_bytes(codex):
    from agents.core.cloud_image_runtime import _write
    from agents.core.media_backends.comfyui import artifact_bytes

    artifact_id = "a" * 32
    source = png()
    _write(codex.root / "media" / "generated" / (artifact_id + ".png"), source)
    task_id = codex.runtime.submit("make blue", {"backend": "openai-codex",
        "model": "gpt-image-2-medium", "references": [artifact_id]}, "user")
    await codex.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await codex.worker.tick()
    assert codex.queue.get(task_id).result["status"] == "ok"
    req = codex.requests[0]
    assert req.url.path.endswith("/images/edits")
    body = json.loads(req.content)
    assert body["images"] == [{"image_url": "data:image/png;base64," + base64.b64encode(source).decode()}]
    assert artifact_bytes(codex.queue.get(task_id).result["result"]["result"]["artifact_id"],
                          codex.root / "media" / "generated")


@pytest.mark.asyncio
async def test_codex_rotation_or_host_change_prevents_dial(codex):
    task_id = codex.runtime.submit("test", {"backend": "openai-codex"}, "user")
    codex.source.base = "https://evil.example/backend-api/codex"
    await codex.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await codex.worker.tick()
    assert codex.requests == []


@pytest.mark.asyncio
async def test_codex_expired_token_prevents_dial(codex):
    task_id = codex.runtime.submit("test", {"backend": "openai-codex"}, "user")
    codex.source.token = _token(expiry=1)
    await codex.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await codex.worker.tick()
    assert codex.requests == []


@pytest.mark.asyncio
async def test_codex_edit_ref_changed_after_approval_prevents_dial(codex):
    from agents.core.cloud_image_runtime import _write

    artifact_id = "c" * 32
    destination = codex.root / "media" / "generated" / (artifact_id + ".png")
    _write(destination, png())
    task_id = codex.runtime.submit("edit", {"backend": "openai-codex",
                                  "references": [artifact_id]}, "user")
    _write(destination, png((1536, 1024)), replace=True)
    await codex.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await codex.worker.tick()
    assert codex.requests == []


@pytest.mark.asyncio
async def test_codex_never_sends_bytes_different_from_approved_digest(codex, monkeypatch):
    import inspect

    from agents.core import cloud_image_runtime

    artifact_id = "d" * 32
    cloud_image_runtime._write(codex.root / "media" / "generated" / (artifact_id + ".png"), png())
    task_id = codex.runtime.submit("edit", {"backend": "openai-codex",
                                  "references": [artifact_id]}, "user")
    original = cloud_image_runtime._reference_bytes

    def changed_only_at_upload(root, refs):
        if inspect.currentframe().f_back.f_code.co_name == "execute":
            return [png((1536, 1024))]
        return original(root, refs)

    monkeypatch.setattr(cloud_image_runtime, "_reference_bytes", changed_only_at_upload)
    await codex.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await codex.worker.tick()
    assert codex.requests == []


@pytest.mark.asyncio
async def test_openai_image2_route_tier_and_multipart_edit(cloud):
    from agents.core.cloud_image_runtime import _write

    artifact_id = "b" * 32
    source = png()
    _write(cloud.root / "media" / "generated" / (artifact_id + ".png"), source)
    task_id = cloud.runtime.submit("edit", {"model": "gpt-image-2-low",
                                             "references": [artifact_id]}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    assert cloud.queue.get(task_id).result["status"] == "ok"
    req = cloud.requests[0]
    assert req.url.path == "/v1/images/edits"
    assert b'gpt-image-2' in req.content and b'name="quality"' in req.content
    assert source in req.content


@pytest.mark.asyncio
async def test_openai_image2_generation_uses_native_body(cloud):
    task_id = cloud.runtime.submit("blue square", {"model": "gpt-image-2-medium"}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    assert cloud.queue.get(task_id).result["status"] == "ok"
    req = cloud.requests[0]
    assert req.url.path == "/v1/images/generations"
    assert json.loads(req.content) == {"model": "gpt-image-2", "prompt": "blue square",
                                       "n": 1, "size": "1024x1024", "quality": "medium"}


def test_provider_status_is_additive_and_unprobed(codex):
    status = codex.runtime.status()
    assert status["model"] == "gpt-image-1.5" and status["reachable"] is None
    assert {"openai", "openai-codex", "fal"} <= set(status["providers"])
    row = status["providers"]["openai-codex"]
    assert row["enabled"] is True and row["configured"] is True
    assert row["default_model"] == "gpt-image-2-medium"
    assert row["model_capabilities"]["gpt-image-2-high"] == {
        "edit": True, "max_reference_images": 16, "reference_kind": "artifact_id"}
    assert row["reachable"] is None and row["reason"] == "not_probed"


def test_disabled_codex_plugin_is_visible_but_not_configured(cloud):
    reads = []
    def source():
        reads.append(True)
        return {"access_token": _token(), "base_url": "https://chatgpt.com/backend-api/codex"}
    cloud.runtime.codex_source = source
    row = cloud.runtime.status()["providers"]["openai-codex"]
    assert row["enabled"] is False
    assert row["configured"] is False
    assert row["reason"] == "disabled"
    assert reads == []


def test_codex_timeout_does_not_change_existing_cloud_provider_deadlines():
    from agents.core.cloud_image_runtime import CODEX_PLUGIN, FAL_PLUGIN, PLUGIN, _Client

    for plugin, expected in ((PLUGIN, 180), (FAL_PLUGIN, 180), (CODEX_PLUGIN, 300)):
        client = _Client(lambda method, url: None, plugin=plugin)
        assert client.timeouts.read == expected
        assert client.timeouts.total == expected


@pytest.mark.asyncio
async def test_actual_registered_tool_proposes_openai_image2_and_codex(codex):
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    orch = SimpleNamespace(agents={}, autonomy=codex.worker, autonomy_queue=codex.queue,
                           cloud_images=codex.runtime, intent_log=None, secret_broker=None)
    AutonomyCoordinator(orch)._wire_agent_tool_runtime(action_kernel=codex.worker.kernel_gate)
    for backend, model, plugin in (
        ("openai", "gpt-image-2-low", "cloud-image"),
        ("openai-codex", "gpt-image-2-high", "cloud-image-codex"),
    ):
        response = await orch.tool_rpc.handle({"tool": "image_generate", "args": {
            "cloud": True, "backend": backend, "model": model, "prompt": "blue square",
        }}, actor="athena")
        assert response["reason"] == "approval_required", response
        task = codex.queue.get(response["task_id"])
        assert task.payload["plugin"] == plugin and task.agent == "athena"
        assert task.autonomy_level == "ask" and task.status == "blocked"
    assert codex.requests == []


@pytest.mark.asyncio
async def test_codex_ambiguous_post_never_replays(codex):
    codex.state.response = lambda: (_ for _ in ()).throw(httpx.ReadError("lost"))
    task_id = codex.runtime.submit("test", {"backend": "openai-codex"}, "user")
    await codex.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await codex.worker.tick()
    task = codex.queue.get(task_id)
    assert task.result["status"] == "unknown"
    assert len(codex.requests) == 1
    assert (await codex.runtime.execute(task))["status"] == "refused"
    assert len(codex.requests) == 1
