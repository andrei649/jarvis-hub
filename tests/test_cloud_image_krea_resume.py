"""A restarted process continues an existing Krea job under a fresh GET approval."""

import asyncio
import json

import httpx
import pytest

from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_openrouter_krea import providers  # noqa: F401
from tests.test_cloud_image_tool import tool  # noqa: F401


async def stranded(providers):
    async def interrupted(_delay):
        raise asyncio.CancelledError

    providers.state.response = lambda: httpx.Response(200, json={"job_id": "durable-job"})
    providers.runtime.poll_sleep = interrupted
    task_id = providers.runtime.submit("blue square", {"backend": "krea"}, "user")
    await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    with pytest.raises(asyncio.CancelledError):
        await providers.worker.tick()
    assert providers.queue.get(task_id).status == "running"
    assert [r.method for r in providers.requests] == ["POST"]
    return task_id


def fresh_runtime(providers):
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.cloud_image_runtime import CloudImageRuntime

    old = providers.runtime
    runtime = CloudImageRuntime(providers.worker, kernel=providers.kernel, redact=lambda s: s,
        root=providers.root, key=old.key, krea_key=old.krea_key, resolver=old.resolver,
        transport_factory=old.transport_factory)

    async def no_wait(_delay):
        return None

    runtime.poll_sleep = no_wait
    executor = TaskExecutor(execution_guard=runtime.guard)
    executor.register("plugin.egress", runtime.execute)
    providers.worker.executor = executor.execute
    providers.runtime = runtime
    return runtime


def result_responses(providers):
    providers.state.response = iter((
        httpx.Response(200, json={"job_id": "durable-job", "status": "completed",
                                 "result": {"url": "https://api.krea.ai/results/durable-job.png"}}),
        httpx.Response(200, content=png((640, 512))),
    )).__next__


@pytest.mark.asyncio
async def test_fresh_runtime_resumes_stranded_job_with_no_generation_post(providers):
    from agents.core.media_library import gallery_page

    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    assert runtime.project(providers.queue.get(source_id)).resume_available is True
    continuation_id = runtime.resume(source_id, "user")
    task = providers.queue.get(continuation_id)
    assert task.payload["method"] == "GET"
    assert task.payload["url"] == "https://api.krea.ai/jobs/durable-job"
    assert task.payload["image"]["resume"]["task_id"] == source_id
    assert task.status == "blocked" and len(providers.requests) == 1
    result_responses(providers)
    await providers.worker.apply_decision(continuation_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(continuation_id)
    assert task.result["status"] == "ok", task.result
    assert [r.method for r in providers.requests] == ["POST", "GET", "GET"]
    assert "authorization" in providers.requests[1].headers
    assert "authorization" not in providers.requests[2].headers
    original = runtime.project(providers.queue.get(source_id))
    resumed = runtime.project(task)
    assert original.state == resumed.state == "ready"
    assert original.artifact.id == resumed.artifact.id
    assert original.resume_available is resumed.resume_available is False
    assert len(gallery_page(providers.root, generated=True)["items"]) == 1


@pytest.mark.asyncio
async def test_two_approved_continuations_share_one_completion(providers):
    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    first = runtime.resume(source_id, "user")
    second = runtime.resume(source_id, "user")
    result_responses(providers)
    for task_id in (first, second):
        await providers.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert providers.queue.get(first).result["status"] == "ok"
    assert providers.queue.get(second).result["status"] == "ok"
    assert [r.method for r in providers.requests] == ["POST", "GET", "GET"]
    assert runtime.project(providers.queue.get(first)).artifact.id == runtime.project(providers.queue.get(second)).artifact.id


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["job", "body", "credential", "approval"])
async def test_resume_rejects_altered_source_before_enqueue(providers, change):
    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    source = providers.queue.get(source_id)
    if change == "job":
        p = runtime._path(source, "job")
        value = json.loads(p.read_text())
        value["binding"] = "0" * 64
        p.write_text(json.dumps(value))
    elif change == "body":
        payload = source.payload
        payload["image"]["body"]["prompt"] = "changed prompt"
        providers.queue.update_payload(source_id, payload)
    elif change == "credential":
        providers.state.key = "rotated credential"
    else:
        providers.queue._conn.execute("UPDATE tasks SET decision='reject' WHERE id=?", (source_id,))
        providers.queue._conn.commit()
    with pytest.raises(ValueError):
        runtime.resume(source_id, "user")
    assert len(providers.queue.list()) == 1
    assert [r.method for r in providers.requests] == ["POST"]


@pytest.mark.asyncio
async def test_resume_rejects_replaced_original_human_approver(providers):
    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    providers.queue._conn.execute(
        "UPDATE tasks SET decided_by='different owner' WHERE id=?", (source_id,)
    )
    providers.queue._conn.commit()
    with pytest.raises(ValueError):
        runtime.resume(source_id, "user")
    assert len(providers.queue.list()) == 1
    assert [request.method for request in providers.requests] == ["POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize("second_state", ["blocked", "rejected", "approved"])
async def test_unexecuted_continuation_does_not_inherit_another_tasks_ready_state(providers, second_state):
    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    first = runtime.resume(source_id, "user")
    second = runtime.resume(source_id, "user")
    if second_state == "rejected":
        await providers.worker.apply_decision(second, "reject", decided_by="test owner")
    result_responses(providers)
    await providers.worker.apply_decision(first, "accept", decided_by="test owner")
    await providers.worker.tick()
    assert runtime.project(providers.queue.get(first)).state == "ready"
    if second_state == "approved":
        await providers.worker.apply_decision(second, "accept", decided_by="test owner")
    view = runtime.project(providers.queue.get(second))
    assert view.state == {"blocked": "awaiting_approval", "rejected": "rejected", "approved": "queued"}[second_state]
    assert view.artifact is None
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source_approval", "credential"])
async def test_poll_stops_before_get_when_source_authority_changes(providers, change):
    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    continuation_id = runtime.resume(source_id, "user")

    async def revoke(_delay):
        if change == "source_approval":
            providers.queue._conn.execute("UPDATE tasks SET decision='reject' WHERE id=?", (source_id,))
            providers.queue._conn.commit()
        else:
            providers.state.key = "rotated credential"

    runtime.poll_sleep = revoke
    result_responses(providers)
    await providers.worker.apply_decision(continuation_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    task = providers.queue.get(continuation_id)
    assert task.result["status"] != "ok"
    assert [request.method for request in providers.requests] == ["POST"]
    assert runtime._path(providers.queue.get(source_id), "complete").exists() is False


@pytest.mark.asyncio
async def test_new_runtime_recovers_durable_completion_after_result_recording_fails(providers):
    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    continuation_id = runtime.resume(source_id, "user")
    result_responses(providers)
    await providers.worker.apply_decision(continuation_id, "accept", decided_by="test owner")
    original_recover = runtime.recover

    def interrupted_recover(task):
        if runtime._path(providers.queue.get(source_id), "complete").exists():
            raise RuntimeError("synthetic crash after durable completion")
        return original_recover(task)

    runtime.recover = interrupted_recover
    await providers.worker.tick()
    assert providers.queue.get(continuation_id).result["status"] != "ok"
    assert runtime._path(providers.queue.get(source_id), "complete").exists()
    restarted = fresh_runtime(providers)
    original = restarted.project(providers.queue.get(source_id))
    resumed = restarted.project(providers.queue.get(continuation_id))
    assert original.state == resumed.state == "ready"
    assert original.artifact.id == resumed.artifact.id
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
async def test_active_source_lock_refuses_resume_without_blocking(providers):
    from agents.core.vault import _file_lock

    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    source = providers.queue.get(source_id)
    with _file_lock(runtime._path(source, "activity.lock"), timeout=0):
        assert runtime.project(source).resume_available is False
        with pytest.raises(ValueError):
            runtime.resume(source_id, "user")
    assert len(providers.queue.list()) == 1


@pytest.mark.asyncio
async def test_resume_route_and_registered_tool_queue_get_only(providers, tool, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    source_id = await stranded(providers)
    runtime = fresh_runtime(providers)
    tool.orch.cloud_images = runtime
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(web, "orch", tool.orch)
    args = {"cloud": True, "backend": "krea", "prompt": "", "resume_task_id": source_id}
    response = TestClient(web.app).post("/api/media/generate", headers={"X-User-Token": "user-token"},
        json={"kind": "image", **args})
    assert response.status_code == 202, response.text
    result = await tool.server.handle({"tool": "image_generate", "args": args}, actor="athena")
    assert result.get("reason") == "approval_required", result
    for task_id in (response.json()["task_id"], result["task_id"]):
        task = providers.queue.get(task_id)
        assert task.payload["method"] == "GET" and task.status == "blocked"
    assert [r.method for r in providers.requests] == ["POST"]
