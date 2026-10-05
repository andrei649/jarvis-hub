"""Real mediated tasks with injected provider HTTP; no live calls or billing."""

import base64
import json

import httpx
import pytest

from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_tool import tool  # noqa: F401


@pytest.fixture
def providers(cloud, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    for plugin in ("cloud-image-openrouter", "cloud-image-krea"):
        monkeypatch.setattr(BUILTIN_PLUGINS[plugin], "enabled", True)
    cloud.runtime.openrouter_key = lambda: cloud.state.key
    cloud.runtime.krea_key = lambda: cloud.state.key

    async def no_wait(_delay):
        return None

    cloud.runtime.poll_sleep = no_wait
    return cloud


def test_new_provider_manifests_are_independent_and_default_off():
    from agents.core.plugin_gate import BUILTIN_PLUGINS, NetworkAccess

    for plugin, host in (("cloud-image-openrouter", "openrouter.ai"),
                         ("cloud-image-krea", "api.krea.ai")):
        row = BUILTIN_PLUGINS[plugin]
        assert row.enabled is False
        assert row.network_access is NetworkAccess.RESTRICTED
        assert row.allowed_domains == ([host, "gen.krea.ai"] if plugin == "cloud-image-krea" else [host])


@pytest.mark.asyncio
async def test_krea_documented_result_origin_downloads_without_credentials(providers):
    providers.state.response = iter((
        httpx.Response(200, json={"job_id": "documented-origin"}),
        httpx.Response(200, json={"job_id": "documented-origin", "status": "completed",
                                  "result": {"urls": ["https://gen.krea.ai/images/source.png"]}}),
        httpx.Response(200, content=png((1024, 64))),
    )).__next__
    task_id = providers.runtime.submit("a lamp", {"backend": "krea"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    assert providers.requests[-1].headers["host"] == "gen.krea.ai"
    assert "authorization" not in providers.requests[-1].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("model,surface", [
    ("openai/gpt-5.4-image-2", "chat/completions"),
    ("openai/gpt-image-2", "images"),
])
async def test_openrouter_route_worker_publishes_measured_artifact(providers, monkeypatch, model, surface):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.media_backends.comfyui import artifact_bytes

    encoded = base64.b64encode(png((640, 512))).decode()
    value = ({"data": [{"b64_json": encoded}]} if surface == "images" else
             {"choices": [{"message": {"images": [{"image_url": {
                 "url": "data:image/png;base64," + encoded}}]}}]})
    providers.state.response = lambda: httpx.Response(200, json=value)
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=providers.runtime))
    response = TestClient(web.app).post("/api/media/generate", headers={"X-User-Token": "user-token"},
        json={"kind": "image", "cloud": True, "backend": "openrouter", "model": model,
              "prompt": "blue square", "size": "1024x1024"})
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    assert not providers.requests
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    assert len(providers.requests) == 1
    assert providers.queue.get(task_id).payload["url"] == "https://openrouter.ai/api/v1/" + surface
    assert providers.requests[0].headers["host"] == "openrouter.ai"
    assert providers.requests[0].url.path == "/api/v1/" + surface
    assert providers.requests[0].headers["authorization"] == "Bearer fixture-credential"
    artifact = task.result["result"]["result"]
    assert (artifact["width"], artifact["height"]) == (640, 512)
    assert artifact_bytes(artifact["artifact_id"], providers.root / "media" / "generated")
    assert providers.runtime.recover(task)["status"] == "ok"
    assert len(providers.requests) == 1


@pytest.mark.asyncio
async def test_openrouter_reference_bytes_bound_to_approval(providers):
    artifact_id = "a" * 32
    directory = providers.root / "media" / "generated"
    directory.mkdir(parents=True)
    original = png((512, 512))
    (directory / (artifact_id + ".png")).write_bytes(original)
    task_id = providers.runtime.submit("variation", {"backend": "openrouter", "references": [artifact_id]}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    (directory / (artifact_id + ".png")).write_bytes(png((640, 512)))
    await providers.worker.tick()
    assert not providers.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["openrouter", "krea"])
async def test_new_provider_ambiguous_post_never_replayed(providers, backend):
    def lost():
        raise httpx.ReadError("untrusted provider details")

    providers.state.response = lost
    task_id = providers.runtime.submit("prompt", {"backend": backend}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(task_id)
    assert task.result["status"] == "unknown", task.result
    assert (await providers.runtime.execute(task))["status"] == "refused"
    assert [request.method for request in providers.requests] == ["POST"]
    assert "untrusted provider details" not in str(task.result)


@pytest.mark.asyncio
async def test_openrouter_url_download_uses_no_provider_credential(providers):
    providers.state.response = iter((
        httpx.Response(200, json={"data": [{"url": "https://openrouter.ai/media/result.png"}]}),
        httpx.Response(200, content=png((640, 512))),
    )).__next__
    task_id = providers.runtime.submit("prompt", {"backend": "openrouter", "model": "openai/gpt-image-2"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(task_id).result["status"] == "ok"
    assert [r.method for r in providers.requests] == ["POST", "GET"]
    assert "authorization" not in providers.requests[1].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://unadmitted.example/result.png", "https://127.0.0.1/result.png"])
async def test_openrouter_unadmitted_download_never_dials(providers, url, monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    providers.state.response = lambda: httpx.Response(200, json={"data": [{"url": url}]})
    task_id = providers.runtime.submit("prompt", {"backend": "openrouter", "model": "openai/gpt-image-2"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(task_id).result["status"] != "ok"
    assert [r.method for r in providers.requests] == ["POST"]


@pytest.mark.asyncio
async def test_krea_job_is_durable_before_poll_and_style_refs_are_signed(providers):
    task_id = None
    responses = iter((
        httpx.Response(200, json={"job_id": "job-1"}),
        httpx.Response(200, json={"job_id": "job-1", "status": "running"}),
        httpx.Response(200, json={"job_id": "job-1", "status": "completed",
                                  "result": {"url": "https://api.krea.ai/results/job-1.png"}}),
        httpx.Response(200, content=png((640, 512))),
    ))

    def response():
        if len(providers.requests) >= 2:
            task = providers.queue.get(task_id)
            record = json.loads(providers.runtime._path(task, "job").read_text())
            assert record["job_id"] == "job-1"
        return next(responses)

    providers.state.response = response
    options = {"backend": "krea", "model": "krea-2-medium", "creativity": "raw",
               "image_style_references": [{"url": "https://styles.example/reference.png", "strength": 0.4}]}
    task_id = providers.runtime.submit("prompt", options, "user")
    body = providers.queue.get(task_id).payload["image"]["body"]
    assert json.loads(body["style_references_json"]) == options["image_style_references"]
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    assert [r.method for r in providers.requests] == ["POST", "GET", "GET", "GET"]
    assert json.loads(providers.requests[0].content)["image_style_references"] == options["image_style_references"]
    assert all(r.headers["authorization"] == "Bearer fixture-credential" for r in providers.requests[:3])
    assert "authorization" not in providers.requests[3].headers


@pytest.mark.asyncio
async def test_krea_revocation_after_submission_prevents_poll(providers, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    def response():
        monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-krea"], "enabled", False)
        return httpx.Response(200, json={"job_id": "job-1"})

    providers.state.response = response
    task_id = providers.runtime.submit("prompt", {"backend": "krea"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(task_id)
    assert providers.runtime._path(task, "job").exists()
    assert task.result["status"] != "ok"
    assert [r.method for r in providers.requests] == ["POST"]


@pytest.mark.asyncio
async def test_krea_revocation_during_poll_dns_retains_governance_reason(providers, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    resolutions = 0

    def resolve(*_args, **_kwargs):
        nonlocal resolutions
        resolutions += 1
        if resolutions == 2:
            monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-krea"], "enabled", False)
        return ["93.184.216.34"], None

    providers.runtime.resolver = resolve
    providers.state.response = lambda: httpx.Response(200, json={"job_id": "job-1"})
    task_id = providers.runtime.submit("prompt", {"backend": "krea"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    result = providers.queue.get(task_id).result
    assert result["status"] == "unknown", result
    assert result["detail"] == "cloud_image_unavailable"
    assert result["job_id"] == "job-1"
    assert [r.method for r in providers.requests] == ["POST"]


def test_discovery_is_local_and_does_not_read_disabled_credentials(cloud):
    def forbidden():
        pytest.fail("disabled provider must not read credential")

    cloud.runtime.openrouter_key = forbidden
    cloud.runtime.krea_key = forbidden
    status = cloud.runtime.status()["providers"]
    for provider in ("openrouter", "krea"):
        assert status[provider]["enabled"] is False
        assert status[provider]["configured"] is False
        assert status[provider]["reachable"] is None
    assert not cloud.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["openrouter", "krea"])
async def test_registered_tool_produces_one_signed_provider_task(providers, tool, backend):
    extra = ({"creativity": "raw", "image_style_references": ["https://styles.example/reference.png"]}
             if backend == "krea" else {"model": "openai/gpt-image-2", "quality": "medium"})
    result = await tool.server.handle({"tool": "image_generate", "args": {
        "cloud": True, "backend": backend, "prompt": "blue square", **extra,
    }}, actor="athena")
    assert result.get("reason") == "approval_required", result
    task = providers.queue.get(result["task_id"])
    assert task.agent == "athena"
    assert task.payload["plugin"] == "cloud-image-" + backend
    providers.runtime.validate(task.payload)
    assert not providers.requests
    if backend == "krea":
        providers.state.response = iter((
            httpx.Response(200, json={"job_id": "tool-job"}),
            httpx.Response(200, json={"job_id": "tool-job", "status": "completed",
                                     "result": {"url": "https://api.krea.ai/results/tool-job.png"}}),
            httpx.Response(200, content=png((640, 512))),
        )).__next__
    await providers.worker.apply_decision(task.id, "accept", decided_by="test owner")
    await providers.worker.tick()
    completed = providers.queue.get(task.id)
    assert completed.result["status"] == "ok", completed.result
    assert sum(r.method == "POST" for r in providers.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    {"job_id": "other-job", "status": "running"},
    {"job_id": "job-1", "status": "failed"},
])
async def test_krea_invalid_or_failed_job_keeps_id_without_publication(providers, status):
    providers.state.response = iter((httpx.Response(200, json={"job_id": "job-1"}),
                                    httpx.Response(200, json=status))).__next__
    task_id = providers.runtime.submit("prompt", {"backend": "krea"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(task_id)
    assert task.result["status"] == "failed", task.result
    assert task.result["job_id"] == "job-1" and task.result["submission_replayed"] is False
    assert [r.method for r in providers.requests] == ["POST", "GET"]
    assert not (providers.root / "media" / "generated").exists()


@pytest.mark.asyncio
async def test_live_gate_owns_result_host_admission(providers, monkeypatch):
    from agents.core.plugin_gate import PermissionGate

    gate = PermissionGate()
    providers.runtime.gate = gate
    monkeypatch.setattr(gate.plugins["cloud-image-openrouter"], "allowed_domains", ["openrouter.ai", "results.example"])
    providers.state.response = iter((
        httpx.Response(200, json={"data": [{"url": "https://results.example/out.png"}]}),
        httpx.Response(200, content=png((640, 512))),
    )).__next__
    task_id = providers.runtime.submit("prompt", {"backend": "openrouter", "model": "openai/gpt-image-2"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(task_id).result["status"] == "ok"
    assert [r.method for r in providers.requests] == ["POST", "GET"]
    assert providers.requests[1].headers["host"] == "results.example"
    assert "authorization" not in providers.requests[1].headers


def test_krea_route_accepts_style_contract_and_local_route_refuses_it(providers, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=providers.runtime))
    client = TestClient(web.app)
    body = {"kind": "image", "cloud": True, "backend": "krea", "prompt": "blue square",
            "creativity": "raw", "image_style_references": [{"url": "https://styles.example/reference.png", "strength": 0.4}]}
    response = client.post("/api/media/generate", headers={"X-User-Token": "user-token"}, json=body)
    assert response.status_code == 202, response.text
    assert len(providers.queue.list()) == 1
    response = client.post("/api/media/generate", headers={"X-User-Token": "user-token"}, json={**body, "cloud": False})
    assert response.status_code == 422
    assert len(providers.queue.list()) == 1 and not providers.requests
