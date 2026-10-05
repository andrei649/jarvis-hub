"""Enhance must keep its source authority and 4K proof through execution."""

import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_krea_enhance import (
    ENHANCED_URL,
    SOURCE_URL,
    completed_source,
    enhance_responses,
    restarted_runtime,
)
from tests.test_cloud_image_krea_resume import stranded
from tests.test_cloud_image_openrouter_krea import providers  # noqa: F401


async def _completed_enhance(providers):
    source_id = await completed_source(providers)
    enhance_id = providers.runtime.enhance(source_id, "user")
    enhance_responses(providers)
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(enhance_id)
    assert task.result["status"] == "ok", task.result
    return source_id, enhance_id, task.result["result"]["result"]["artifact_id"]


def _client(providers, monkeypatch):
    from agents import web

    monkeypatch.setenv("JARVIS_HOME", str(providers.root))
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=providers.runtime))
    return TestClient(web.app)


def _change_source(providers, source_id, change):
    source = providers.queue.get(source_id)
    if change == "artifact":
        artifact_id = source.result["result"]["result"]["artifact_id"]
        (providers.root / "media" / "generated" / (artifact_id + ".png")).write_bytes(png((1024, 128)))
    else:
        providers.queue._conn.execute("UPDATE tasks SET decision='reject' WHERE id=?", (source_id,))
        providers.queue._conn.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "symlink", "sha256", "task_id"])
async def test_4k_artifact_route_rejects_missing_or_changed_private_proof(providers, monkeypatch, change):
    source_id, _, artifact_id = await _completed_enhance(providers)
    path = providers.runtime.records / (artifact_id + ".artifact")
    assert path.exists()
    if change == "missing":
        path.unlink()
    elif change == "symlink":
        path.unlink()
        target = providers.root / "untrusted-proof.json"
        target.write_text("{}")
        path.symlink_to(target)
    else:
        proof = json.loads(path.read_text())
        proof[change] = "0" * 64 if change == "sha256" else source_id
        path.write_text(json.dumps(proof))
    response = _client(providers, monkeypatch).get(
        "/api/media/generated/" + artifact_id, headers={"X-User-Token": "user-token"})
    assert response.status_code == 404
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST", "GET", "GET"]


@pytest.mark.asyncio
async def test_naked_4k_png_cannot_use_normal_artifact_fallback(providers, monkeypatch):
    artifact_id = "a" * 32
    folder = providers.root / "media" / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (artifact_id + ".png")).write_bytes(png((4096, 128)))
    response = _client(providers, monkeypatch).get(
        "/api/media/generated/" + artifact_id, headers={"X-User-Token": "user-token"})
    assert response.status_code == 404
    assert providers.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["artifact", "decision"])
async def test_source_change_after_enhance_proposal_blocks_dial(providers, change):
    source_id = await completed_source(providers)
    enhance_id = providers.runtime.enhance(source_id, "user")
    _change_source(providers, source_id, change)
    enhance_responses(providers)
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(enhance_id).result.get("status") != "ok"
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
async def test_source_result_host_withdrawn_after_proposal_blocks_enhance_dial(providers, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    source_url = "https://gen.krea.ai/images/approved-source.png"
    providers.state.response = iter((
        httpx.Response(200, json={"job_id": "source-job"}),
        httpx.Response(200, json={"job_id": "source-job", "status": "completed",
                                  "result": {"urls": [source_url]}}),
        httpx.Response(200, content=png((2048, 64))),
    )).__next__
    source_id = providers.runtime.submit("a lamp", {
        "backend": "krea", "model": "krea-2-medium", "size": "1536x1024"}, "user")
    await providers.worker.apply_decision(source_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(source_id).result["status"] == "ok"
    enhance_id = providers.runtime.enhance(source_id, "user")
    assert providers.queue.get(enhance_id).payload["image"]["body"]["image_url"] == source_url
    monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image-krea"], "allowed_domains", ["api.krea.ai"])
    enhance_responses(providers)
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(enhance_id).result.get("status") != "ok"
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["post", "result"])
@pytest.mark.parametrize("change", ["artifact", "decision"])
async def test_source_change_during_enhance_rejects_result_without_replay(providers, phase, change):
    source_id = await completed_source(providers)
    enhance_id = providers.runtime.enhance(source_id, "user")
    enhance_responses(providers)
    responses = providers.state.response
    target_count = 4 if phase == "post" else 6

    def changed_response():
        if len(providers.requests) == target_count:
            _change_source(providers, source_id, change)
        return responses()

    providers.state.response = changed_response
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(enhance_id)
    assert task.result["status"] != "ok"
    assert len(providers.requests) == target_count
    assert (await providers.runtime.execute(task))["status"] == "refused"
    assert len(providers.requests) == target_count
    assert not providers.runtime._path(task, "complete").exists()


@pytest.mark.asyncio
async def test_completed_original_continuation_can_be_selected_but_enhance_cannot_nest(providers):
    source_id = await stranded(providers)
    runtime = restarted_runtime(providers)
    continuation_id = runtime.resume(source_id, "user")
    providers.state.response = iter((
        httpx.Response(200, json={"job_id": "durable-job", "status": "completed",
                                  "result": {"url": SOURCE_URL}}),
        httpx.Response(200, content=png((2048, 64))),
    )).__next__
    await providers.worker.apply_decision(continuation_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(continuation_id).result["status"] == "ok"
    enhance_id = runtime.enhance(continuation_id, "user")
    assert providers.queue.get(enhance_id).payload["image"]["enhance"]["task_id"] == source_id
    assert len(providers.requests) == 3
    with pytest.raises(ValueError):
        runtime.enhance(enhance_id, "user")
    enhance_responses(providers)
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(enhance_id).result["status"] == "ok"
    with pytest.raises(ValueError):
        runtime.enhance(enhance_id, "user")
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST", "GET", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "artifact_id", "resume_post"])
async def test_enhance_resume_descriptor_cannot_be_stripped_or_retargeted(providers, change):
    source_id = await completed_source(providers)
    enhance_id = providers.runtime.enhance(source_id, "user")

    async def interrupted(_delay):
        raise asyncio.CancelledError

    providers.runtime.poll_sleep = interrupted
    providers.state.response = lambda: httpx.Response(200, json={"job_id": "enhance-job"})
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    with pytest.raises(asyncio.CancelledError):
        await providers.worker.tick()
    runtime = restarted_runtime(providers)
    continuation_id = runtime.resume(enhance_id, "user")
    payload = copy.deepcopy(providers.queue.get(continuation_id).payload)
    if change == "missing":
        del payload["image"]["enhance"]
    elif change == "artifact_id":
        payload["image"]["enhance"]["artifact_id"] = "0" * 32
    else:
        payload["method"] = "POST"
        payload["url"] = "https://api.krea.ai/generate/enhance/krea/enhance"
    with pytest.raises(ValueError):
        runtime.validate(payload)
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST"]
