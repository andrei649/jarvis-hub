"""A second Krea Enhance payment needs its own signed approval and saved pixels."""

import asyncio
import hashlib
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_openrouter_krea import providers  # noqa: F401
from tests.test_cloud_image_tool import tool  # noqa: F401

SOURCE_URL = "https://api.krea.ai/results/source-job.png"
ENHANCED_URL = "https://api.krea.ai/results/enhance-job.png"


async def completed_source(providers):
    providers.state.response = iter((
        httpx.Response(200, json={"job_id": "source-job"}),
        httpx.Response(200, json={"job_id": "source-job", "status": "completed",
                                  "result": {"url": SOURCE_URL}}),
        httpx.Response(200, content=png((2048, 64))),
    )).__next__
    source_id = providers.runtime.submit("a lamp", {
        "backend": "krea", "model": "krea-2-medium", "size": "1536x1024"}, "user")
    await providers.worker.apply_decision(source_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    source = providers.queue.get(source_id)
    assert source.result["status"] == "ok", source.result
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET"]
    assert providers.runtime.project(source).state == "ready"
    return source_id


def enhance_responses(providers):
    encoded = io.BytesIO()
    exif = Image.Exif()
    exif[270] = "untrusted provider metadata"
    Image.new("RGB", (4096, 128), "blue").save(encoded, format="PNG", exif=exif)
    providers.state.response = iter((
        httpx.Response(200, json={"job_id": "enhance-job"}),
        httpx.Response(200, json={"job_id": "enhance-job", "status": "completed",
                                  "result": {"url": ENHANCED_URL}}),
        httpx.Response(200, content=encoded.getvalue()),
    )).__next__


def restarted_runtime(providers):
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.cloud_image_runtime import CloudImageRuntime

    prior = providers.runtime
    runtime = CloudImageRuntime(providers.worker, kernel=providers.kernel, redact=lambda s: s,
        root=providers.root, key=prior.key, krea_key=prior.krea_key, resolver=prior.resolver,
        transport_factory=prior.transport_factory)

    async def no_wait(_delay):
        return None

    runtime.poll_sleep = no_wait
    executor = TaskExecutor(execution_guard=runtime.guard)
    executor.register("plugin.egress", runtime.execute)
    providers.worker.executor = executor.execute
    providers.runtime = runtime
    return runtime


@pytest.mark.asyncio
async def test_enhance_is_separate_signed_post_with_clean_4k_artifact_and_original_preserved(providers, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.media_backends.comfyui import ImageGenerationError, artifact_bytes
    from agents.core.media_library import gallery_page

    source_id = await completed_source(providers)
    source = providers.queue.get(source_id)
    source_artifact = source.result["result"]["result"]
    source_bytes = artifact_bytes(source_artifact["artifact_id"], providers.root / "media" / "generated")
    assert providers.runtime.project(source).enhance_available is True
    task_id = providers.runtime.enhance(source_id, "user")
    task = providers.queue.get(task_id)
    assert task.kind == "plugin.egress" and task.status == "blocked" and task.autonomy_level == "ask"
    assert task.payload["plugin"] == "cloud-image-krea"
    assert task.payload["method"] == "POST"
    assert task.payload["url"] == "https://api.krea.ai/generate/enhance/krea/enhance"
    assert task.payload["image"]["body"] == {
        "model": "krea-2-medium", "prompt": "a lamp", "size": "1536x1024",
        "operation": "enhance", "image_url": SOURCE_URL, "image_scaling_factor": 2,
    }
    descriptor = task.payload["image"]["enhance"]
    assert set(descriptor) == {"task_id", "nonce", "binding", "artifact_id", "sha256"}
    assert descriptor["task_id"] == source_id
    assert descriptor["nonce"] == source.payload["image"]["nonce"]
    assert descriptor["artifact_id"] == source_artifact["artifact_id"]
    assert descriptor["sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert len(providers.requests) == 3, "Enhance must not dial before its own approval"
    enhance_responses(providers)
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST", "GET", "GET"]
    assert providers.requests[3].url.path == "/generate/enhance/krea/enhance"
    assert json.loads(providers.requests[3].content) == {
        "image_url": SOURCE_URL, "image_scaling_factor": 2, "prompt": "a lamp"}
    assert "authorization" in providers.requests[3].headers
    assert "authorization" not in providers.requests[5].headers
    enhanced = task.result["result"]["result"]
    assert enhanced["artifact_id"] != source_artifact["artifact_id"]
    assert (enhanced["width"], enhanced["height"]) == (4096, 128)
    assert artifact_bytes(source_artifact["artifact_id"], providers.root / "media" / "generated") == source_bytes
    with pytest.raises(ImageGenerationError):
        artifact_bytes(enhanced["artifact_id"], providers.root / "media" / "generated")
    assert len(gallery_page(providers.root, generated=True)["items"]) == 2

    monkeypatch.setenv("JARVIS_HOME", str(providers.root))
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=providers.runtime, autonomy_queue=providers.queue))
    client = TestClient(web.app)
    status = client.get(f"/api/media/generation-tasks/{task_id}", headers={"X-Admin-Token": "owner-token"})
    assert status.status_code == 200 and status.json()["state"] == "ready"
    image = client.get("/api/media/generated/" + enhanced["artifact_id"],
        headers={"X-User-Token": "user-token"})
    assert image.status_code == 200, image.text[:120] if image.status_code != 200 else ""
    with Image.open(io.BytesIO(image.content)) as raster:
        assert raster.size == (4096, 128) and not raster.info
    assert len(providers.requests) == 6


@pytest.mark.asyncio
async def test_interrupted_enhance_resumes_saved_job_with_get_only(providers):
    source_id = await completed_source(providers)
    enhance_id = providers.runtime.enhance(source_id, "user")

    async def interrupted(_delay):
        raise asyncio.CancelledError

    providers.runtime.poll_sleep = interrupted
    providers.state.response = lambda: httpx.Response(200, json={"job_id": "enhance-job"})
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    with pytest.raises(asyncio.CancelledError):
        await providers.worker.tick()
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST"]
    enhancement = providers.queue.get(enhance_id)
    assert providers.runtime._path(enhancement, "job").exists()
    runtime = restarted_runtime(providers)
    continuation_id = runtime.resume(enhance_id, "user")
    continuation = providers.queue.get(continuation_id)
    assert continuation.status == "blocked" and continuation.payload["method"] == "GET"
    assert continuation.payload["image"]["enhance"] == enhancement.payload["image"]["enhance"]
    assert len(providers.requests) == 4
    providers.state.response = iter((
        httpx.Response(200, json={"job_id": "enhance-job", "status": "completed",
                                  "result": {"url": ENHANCED_URL}}),
        httpx.Response(200, content=png((4096, 128))),
    )).__next__
    await providers.worker.apply_decision(continuation_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(continuation_id).result["status"] == "ok"
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST", "GET", "GET"]
    assert runtime.project(providers.queue.get(source_id)).state == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["artifact", "approver", "credential", "job", "result_url"])
async def test_enhance_refuses_changed_source_before_new_approval(providers, change):
    source_id = await completed_source(providers)
    source = providers.queue.get(source_id)
    if change == "artifact":
        artifact_id = source.result["result"]["result"]["artifact_id"]
        (providers.root / "media" / "generated" / (artifact_id + ".png")).write_bytes(png((1024, 128)))
    elif change == "approver":
        providers.queue._conn.execute("UPDATE tasks SET decided_by='different owner' WHERE id=?", (source_id,))
        providers.queue._conn.commit()
    elif change == "credential":
        providers.state.key = "rotated credential"
    elif change == "job":
        path = providers.runtime._path(source, "job")
        record = json.loads(path.read_text())
        record["job_id"] = "other-job"
        path.write_text(json.dumps(record))
    else:
        path = providers.runtime._path(source, "complete")
        record = json.loads(path.read_text())
        record["provider_result_url"] = "https://api.krea.ai/results/other.png"
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        providers.runtime.enhance(source_id, "user")
    assert len(providers.queue.list()) == 1
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
async def test_enhance_route_and_tool_queue_one_new_approval_without_network(providers, tool, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    source_id = await completed_source(providers)
    tool.orch.cloud_images = providers.runtime
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", tool.orch)
    args = {"cloud": True, "backend": "krea", "prompt": "", "enhance_task_id": source_id}
    response = TestClient(web.app).post("/api/media/generate", headers={"X-User-Token": "user-token"},
        json={"kind": "image", **args})
    assert response.status_code == 202, response.text
    result = await tool.server.handle({"tool": "image_generate", "args": args}, actor="athena")
    assert result.get("reason") == "approval_required", result
    for task_id in (response.json()["task_id"], result["task_id"]):
        task = providers.queue.get(task_id)
        assert task.status == "blocked" and task.payload["method"] == "POST"
        assert task.payload["url"] == "https://api.krea.ai/generate/enhance/krea/enhance"
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_response", ["lost", "failed"])
async def test_failed_or_ambiguous_enhance_never_replays_and_keeps_original_ready(providers, provider_response):
    source_id = await completed_source(providers)
    enhance_id = providers.runtime.enhance(source_id, "user")

    def response():
        if provider_response == "lost":
            raise httpx.ReadError("untrusted Krea details")
        return httpx.Response(503)

    providers.state.response = response
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(enhance_id)
    assert task.result["status"] != "ok"
    assert (await providers.runtime.execute(task))["status"] == "refused"
    assert providers.runtime.project(providers.queue.get(source_id)).state == "ready"
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST"]
