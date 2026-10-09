"""Owner-only, bounded task projection for the image composer."""
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core.image_generation_view import project_image_task
from agents.core.media_backends.openai_image import ENDPOINT
from agents.core.routers import multimodal


def image_task(*, status="done", result=None, kind="toolrpc.image_generate"):
    return SimpleNamespace(id=17, kind=kind, status=status, payload={"tool": "image_generate", "target": "image_generate", "args": {"prompt": "PRIVATE", "_binding": "PRIVATE"}}, result=result)


def success(**overrides):
    return {"status": "ok", "tool": "image_generate", "result": {"ok": True, "kind": "image", "result": {
        "artifact_id": "a" * 32, "bytes": 80, "width": 512, "height": 512,
        "path": "C:/PRIVATE/image.png", "url": "https://evil.invalid/PRIVATE", **overrides,
    }}}


def cloud_task(*, status="done", result=None, task_id=17):
    return SimpleNamespace(
        id=task_id, kind="plugin.egress", status=status,
        payload={"plugin": "cloud-image", "method": "POST", "url": ENDPOINT,
                 "image": {"body": {"prompt": "PRIVATE"}}}, result=result,
    )


def local_response_failure(reason="invalid_response", marker="local_openai_images_v1"):
    return {"status": "failed", "reason": reason, "tool": "image_generate", "result": {
        "ok": False, "reason": reason, "provider_response_failed": marker,
    }}


@pytest.fixture
def app(monkeypatch):
    from agents.core.routers import _component
    app = FastAPI()
    app.include_router(multimodal.router)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    monkeypatch.setattr(_component, "get_orch", lambda: multimodal.get_orch())
    return app


@pytest.mark.parametrize("kind", ["toolrpc.image_generate", "tool.rpc"])
@pytest.mark.asyncio
async def test_owner_projection_redacts_payload_paths_urls_and_unrelated_results(app, monkeypatch, kind):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=lambda task_id: image_task(kind=kind, result=success()))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 200
    assert response.json() == {"task_id": 17, "state": "ready", "resume_available": False,
                               "enhance_available": False,
                               "artifact": {"id": "a" * 32, "bytes": 80, "width": 512, "height": 512}}
    assert "PRIVATE" not in response.text
    assert "url" not in response.json()["artifact"]


@pytest.mark.parametrize("overrides", [{"tool": "other"}, {"target": "other"}, {"target": None}, {"tool": None}])
@pytest.mark.asyncio
async def test_canonical_tool_task_requires_exact_image_identity(app, monkeypatch, overrides):
    task = image_task(kind="tool.rpc", result=success())
    task.payload.update(overrides)
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=lambda task_id: task)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 404
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("result", [None, [], 12, {"status": "failed", "reason": "submission_unknown", "secret": "PRIVATE"}, success(artifact_id="../secret"), success(bytes=0), success(bytes=True), success(width=999999), success(height=False), {**success(), "status": "failed"}, {**success(), "tool": "different"}, {**success(), "result": {"ok": "true"}}])
@pytest.mark.asyncio
async def test_done_without_valid_success_is_uncertain_not_generated(app, monkeypatch, result):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=lambda task_id: image_task(result=result))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.json() == {"task_id": 17, "state": "uncertain", "artifact": None,
                               "resume_available": False, "enhance_available": False}


@pytest.mark.parametrize("status,state", [("blocked", "awaiting_approval"), ("proposed", "awaiting_approval"), ("approved", "queued"), ("running", "generating"), ("rejected", "rejected"), ("deferred", "deferred"), ("failed", "uncertain"), ("quarantined", "refused")])
@pytest.mark.asyncio
async def test_exact_queue_states_are_projected_without_inventing_progress(app, monkeypatch, status, state):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=lambda task_id: image_task(status=status))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.json() == {"task_id": 17, "state": state, "artifact": None,
                               "resume_available": False, "enhance_available": False}


@pytest.mark.asyncio
async def test_projection_requires_admin_and_rejects_non_image_kind_before_serialization(app, monkeypatch):
    calls = []
    def get(task_id):
        calls.append(task_id)
        return image_task(kind="toolrpc.image_generate_evil", result=success())
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=get)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/media/generation-tasks/17")).status_code == 401
        assert calls == []
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
        assert response.status_code == 404
        assert "PRIVATE" not in response.text


@pytest.mark.parametrize("task_id", ["0", "-1", str(2**63), "nonnumeric"])
@pytest.mark.asyncio
async def test_invalid_task_id_never_reaches_durable_store(app, monkeypatch, task_id):
    def forbidden(task_id):
        pytest.fail("invalid ID reached the durable store")
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=SimpleNamespace(get=forbidden)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get(f"/api/media/generation-tasks/{task_id}", headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 422


@pytest.mark.parametrize("queue", [None, SimpleNamespace(get=lambda task_id: None)])
@pytest.mark.asyncio
async def test_unavailable_queue_and_missing_task_are_explicit(app, monkeypatch, queue):
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(autonomy_queue=queue))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == (503 if queue is None else 404)
    assert response.json() == {"error": "image task state not available" if queue is None else "image task not found"}


@pytest.mark.parametrize("reason", [
    "cloud_image_provider_error", "cloud_image_response_too_large", "cloud_image_invalid_response",
])
@pytest.mark.asyncio
async def test_exact_cloud_provider_response_failure_has_only_safe_terminal_state(app, monkeypatch, reason):
    task = cloud_task(result={"status": "failed", "reason": reason})
    project = Mock(side_effect=project_image_task)
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(
        autonomy_queue=SimpleNamespace(get=lambda _task_id: task),
        cloud_images=SimpleNamespace(project=project),
    ))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/media/generation-tasks/17")).status_code == 401
        response = await client.get(
            "/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"},
        )
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == {"task_id": 17, "state": "failed", "artifact": None,
        "resume_available": False, "enhance_available": False}
    assert reason not in response.text and "PRIVATE" not in response.text
    project.assert_called_once_with(task)


@pytest.mark.parametrize("task_id,returned_id", [(17, 18), (1, True), (17, "17"), (1, 0)])
@pytest.mark.asyncio
async def test_cloud_identity_mismatch_is_refused_before_runtime_projection(
    app, monkeypatch, task_id, returned_id,
):
    project = Mock(side_effect=AssertionError("wrong row reached cloud runtime"))
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(
        autonomy_queue=SimpleNamespace(get=lambda _task_id: cloud_task(
            task_id=returned_id, result={"status": "failed", "reason": "cloud_image_provider_error"},
        )),
        cloud_images=SimpleNamespace(project=project),
    ))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            f"/api/media/generation-tasks/{task_id}", headers={"X-Admin-Token": "owner-test"},
        )
    assert response.status_code == 404
    project.assert_not_called()


@pytest.mark.parametrize("change", [
    {"status": "failed"},
    {"kind": "plugin.egress.other"},
    {"plugin": "other"},
    {"method": "GET"},
    {"url": "https://other.test/v1/images/generations"},
    {"result": {"status": "failed", "reason": "cloud_image_provider_error", "detail": "PRIVATE"}},
    {"result": {"status": "unknown", "reason": "cloud_image_provider_error"}},
    {"result": {"status": "failed", "reason": "withheld_after_generation"}},
    {"result": {"status": "failed", "reason": "cloud_image_recheck_failed"}},
    {"result": {"status": "failed", "reason": "cloud_image_preflight_failed"}},
    {"result": {"status": "failed", "reason": "mediation_state_unavailable"}},
    {"result": {"status": "failed", "reason": "submission_unknown"}},
    {"result": {"status": "failed", "reason": True}},
    {"result": {"status": "failed", "reason": ["cloud_image_provider_error"]}},
    {"result": type("ResultDict", (dict,), {})({"status": "failed", "reason": "cloud_image_provider_error"})},
    {"payload": type("PayloadDict", (dict,), {})({"plugin": "cloud-image", "method": "POST", "url": ENDPOINT})},
    {"result": success()},
])
def test_unmatched_cloud_envelopes_remain_uncertain(change):
    task = cloud_task(result={"status": "failed", "reason": "cloud_image_provider_error"})
    for key, value in change.items():
        if key in {"plugin", "method", "url"}:
            task.payload[key] = value
        else:
            setattr(task, key, value)
    assert project_image_task(task).model_dump() == {
        "task_id": 17, "state": "uncertain", "artifact": None,
        "resume_available": False, "enhance_available": False,
    }


def test_local_image_failure_envelope_does_not_inherit_cloud_failure_label():
    task = image_task(result={
        "status": "failed", "tool": "image_generate", "reason": "cloud_image_provider_error",
        "result": {"ok": False, "kind": "image", "reason": "cloud_image_provider_error"},
    })
    assert project_image_task(task).state == "uncertain"


@pytest.mark.parametrize("reason", [
    "backend_http_error", "invalid_response", "response_too_large",
    "invalid_image", "image_dimensions_mismatch",
])
@pytest.mark.asyncio
async def test_exact_local_provider_response_failure_is_redacted_and_admin_only(app, monkeypatch, reason):
    task = image_task(kind="tool.rpc", result=local_response_failure(reason))
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(
        autonomy_queue=SimpleNamespace(get=lambda _task_id: task),
    ))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/media/generation-tasks/17")).status_code == 401
        response = await client.get(
            "/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"},
        )
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == {"task_id": 17, "state": "failed", "artifact": None,
        "resume_available": False, "enhance_available": False}
    assert reason not in response.text and "PRIVATE" not in response.text
    assert "local_openai_images_v1" not in response.text


@pytest.mark.parametrize("change", [
    {"status": "failed"},
    {"kind": "toolrpc.image_generate"},
    {"kind": "plugin.egress"},
    {"payload": {"tool": "image_generate", "target": "other"}},
    {"payload": {"tool": "other", "target": "image_generate"}},
    {"payload": type("PayloadDict", (dict,), {})({"tool": "image_generate", "target": "image_generate"})},
    {"result": {"status": "failed", "reason": "invalid_response", "tool": "image_generate",
                "result": {"ok": False, "reason": "invalid_response"}}},
    {"result": {**local_response_failure(), "detail": "PRIVATE"}},
    {"result": {**local_response_failure(), "tool": "other"}},
    {"result": {**local_response_failure(), "status": "unknown"}},
    {"result": {**local_response_failure(), "reason": "submission_unknown"}},
    {"result": {**local_response_failure(), "reason": True}},
    *[{"result": local_response_failure(reason)} for reason in (
        "generation_failed", "submission_unknown", "withheld_after_generation",
    )],
    {"result": {**local_response_failure(), "result": {"ok": False, "reason": "invalid_response",
                "provider_response_failed": "local_openai_images_v1", "body": "PRIVATE"}}},
    {"result": {**local_response_failure(), "result": {"ok": True, "reason": "invalid_response",
                "provider_response_failed": "local_openai_images_v1"}}},
    {"result": {**local_response_failure(), "result": {"ok": 0, "reason": "invalid_response",
                "provider_response_failed": "local_openai_images_v1"}}},
    {"result": {**local_response_failure(), "result": {"ok": False, "reason": "other",
                "provider_response_failed": "local_openai_images_v1"}}},
    {"result": {**local_response_failure(), "result": {"ok": False, "reason": "invalid_response",
                "provider_response_failed": "other"}}},
    {"result": {**local_response_failure(), "result": {"ok": False, "reason": "invalid_response",
                "provider_response_failed": True}}},
    {"result": type("ResultDict", (dict,), {})(local_response_failure())},
    {"result": {**local_response_failure(), "result": type("NestedDict", (dict,), {})(
                local_response_failure()["result"])}},
])
def test_local_failure_requires_exact_canonical_envelope(change):
    task = image_task(kind="tool.rpc", result=local_response_failure())
    for key, value in change.items():
        setattr(task, key, value)
    assert project_image_task(task).model_dump() == {
        "task_id": 17, "state": "uncertain", "artifact": None,
        "resume_available": False, "enhance_available": False,
    }


def test_local_legacy_and_comfyui_failure_reasons_remain_uncertain():
    for reason in ("generation_failed", "invalid_response", "backend_http_error"):
        task = image_task(kind="tool.rpc", result={
            "status": "failed", "reason": reason, "tool": "image_generate",
            "result": {"ok": False, "reason": reason},
        })
        assert project_image_task(task).state == "uncertain"


@pytest.mark.asyncio
async def test_exact_comfyui_history_error_is_redacted_and_admin_only(app, monkeypatch):
    task = image_task(kind="tool.rpc", result=local_response_failure(
        "generation_failed", "comfyui_history_error_v1",
    ))
    monkeypatch.setattr(multimodal, "get_orch", lambda: SimpleNamespace(
        autonomy_queue=SimpleNamespace(get=lambda _task_id: task),
    ))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/media/generation-tasks/17")).status_code == 401
        response = await client.get(
            "/api/media/generation-tasks/17", headers={"X-Admin-Token": "owner-test"},
        )
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == {"task_id": 17, "state": "failed", "artifact": None,
        "resume_available": False, "enhance_available": False}
    assert "generation_failed" not in response.text
    assert "comfyui_history_error_v1" not in response.text
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("result", [
    local_response_failure("generation_failed", "local_openai_images_v1"),
    local_response_failure("invalid_response", "comfyui_history_error_v1"),
    local_response_failure("generation_failed", "comfyui_history_error_v2"),
    {**local_response_failure("generation_failed", "comfyui_history_error_v1"), "detail": "PRIVATE"},
    {**local_response_failure("generation_failed", "comfyui_history_error_v1"), "reason": "other"},
    {**local_response_failure("generation_failed", "comfyui_history_error_v1"),
     "result": {"ok": False, "reason": "other", "provider_response_failed": "comfyui_history_error_v1"}},
    {**local_response_failure("generation_failed", "comfyui_history_error_v1"),
     "result": {"ok": 0, "reason": "generation_failed", "provider_response_failed": "comfyui_history_error_v1"}},
    {**local_response_failure("generation_failed", "comfyui_history_error_v1"),
     "result": {"ok": False, "reason": "generation_failed", "provider_response_failed": True}},
])
def test_comfyui_marker_and_reason_must_be_exactly_paired(result):
    task = image_task(kind="tool.rpc", result=result)
    assert project_image_task(task).model_dump() == {
        "task_id": 17, "state": "uncertain", "artifact": None,
        "resume_available": False, "enhance_available": False,
    }
