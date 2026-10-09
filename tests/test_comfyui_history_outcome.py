"""One pinned ComfyUI history error, through transport and signed execution."""

import json
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from agents.core.media_backends import comfyui
from tests.test_image_mediation_composition import composed, proposal  # noqa: F401
from tests.test_local_image_backend import PNG, configured, output_history


def _error_history(messages=None):
    return {"p-1": {"status": {
        "status_str": "error", "completed": False,
        "messages": [] if messages is None else messages,
    }, "outputs": {}}}


def _service(request, history, calls):
    calls.append(request)
    if request.url.path == "/prompt":
        return httpx.Response(200, json={"prompt_id": "p-1"})
    if request.url.path == "/history/p-1":
        return httpx.Response(200, json=history)
    raise AssertionError("error history must not fetch an image")


@pytest.mark.parametrize("message", ["execution_error", "execution_interrupted"])
@pytest.mark.asyncio
async def test_exact_history_error_is_typed_and_never_fetches_or_publishes(tmp_path, message):
    calls = []
    history = _error_history([[message, {"exception_message": "PRIVATE"}]])
    backend = comfyui.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(
        lambda req: _service(req, history, calls)))

    with pytest.raises(comfyui._ComfyHistoryError) as found:
        await backend.generate("blue boat", {})

    assert found.value.reason == comfyui._HISTORY_ERROR_REASON == "generation_failed"
    assert comfyui._HISTORY_ERROR_MARKER == "comfyui_history_error_v1"
    assert [request.url.path for request in calls] == ["/prompt", "/history/p-1"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("history", [
    {"p-2": _error_history()["p-1"]},
    {"p-1": _error_history()["p-1"], "p-2": _error_history()["p-1"]},
    {"p-1": {"status": {"status_str": "error", "completed": True, "messages": []}}},
    {"p-1": {"status": {"status_str": "error", "completed": 0, "messages": []}}},
    {"p-1": {"status": {"status_str": "error", "messages": []}}},
    {"p-1": {"status": {"status_str": "error", "completed": False}}},
    {"p-1": {"status": {"status_str": "error", "completed": False, "messages": "PRIVATE"}}},
    {"p-1": {"status": {"status_str": "error", "completed": False, "messages": [], "extra": 1}}},
    {"p-1": {"status": {"status_str": "running", "completed": False, "messages": []}}},
    {"p-1": {"status": {"status_str": "success", "completed": False, "messages": []}}},
    {"p-1": {"status": []}},
    {"p-1": []},
    {"p-1": {"status": {"status_str": "success", "completed": True, "messages": []},
              "outputs": {"9": {"images": []}}}},
])
@pytest.mark.asyncio
async def test_other_history_shapes_never_mint_error_type(tmp_path, history):
    calls = []
    config = configured(tmp_path)
    config = type(config)(**{**vars(config), "timeout": 0.04, "poll_interval": 0.005})
    backend = comfyui.ComfyUIBackend(config, transport=httpx.MockTransport(
        lambda req: _service(req, history, calls)))

    with pytest.raises(comfyui.ImageGenerationError) as found:
        await backend.generate("blue boat", {})
    assert type(found.value) is comfyui.ImageGenerationError
    assert sum(req.url.path == "/prompt" for req in calls) == 1
    assert not any(req.url.path == "/view" for req in calls)


@pytest.mark.parametrize("stage,wire", [
    ("prompt", b'{"prompt_id":"p-1","prompt_id":"p-2"}'),
    ("prompt", b'{"prompt_id":"p-1","number":NaN}'),
    ("prompt", b'{"prompt_id":"p-1","number":1e10000}'),
    ("history", b'{"p-1":{"status":{"status_str":"error","completed":false,"messages":[]}},'
                b'"p-1":{"status":{"status_str":"error","completed":false,"messages":[]}}}'),
    ("history", b'{"p-1":{"status":{"status_str":"error","status_str":"error",'
                b'"completed":false,"messages":[]}}}'),
    ("history", b'{"p-1":{"status":{"status_str":"error","completed":false,'
                b'"messages":[]},"extra":Infinity}}'),
])
@pytest.mark.asyncio
async def test_duplicate_or_nonfinite_json_cannot_mint_history_evidence(tmp_path, stage, wire):
    calls = []

    def service(request):
        calls.append(request)
        if request.url.path == "/prompt":
            return httpx.Response(200, content=wire if stage == "prompt" else b'{"prompt_id":"p-1"}')
        if request.url.path == "/history/p-1":
            return httpx.Response(200, content=wire)
        raise AssertionError(request.url)

    config = configured(tmp_path)
    config = type(config)(**{**vars(config), "timeout": 0.04, "poll_interval": 0.005})
    backend = comfyui.ComfyUIBackend(config, transport=httpx.MockTransport(service))
    with pytest.raises(comfyui.ImageGenerationError) as found:
        await backend.generate("blue boat", {})
    assert type(found.value) is comfyui.ImageGenerationError
    assert found.value.reason == "invalid_response"
    assert not any(req.url.path == "/view" for req in calls)


@pytest.mark.asyncio
async def test_valid_history_json_still_accepts_success(tmp_path):
    from tests.test_local_image_backend import PNG

    calls = []

    def service(request):
        calls.append(request)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        if request.url.path == "/history/p-1":
            return httpx.Response(200, json=output_history())
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    backend = comfyui.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    result = await backend.generate("blue boat", {})
    assert result["bytes"] == len(PNG)
    assert len([req for req in calls if req.method == "POST"]) == 1


@pytest.mark.parametrize("message", ["execution_error", "execution_interrupted"])
@pytest.mark.asyncio
async def test_signed_worker_carries_only_fixed_history_marker(composed, monkeypatch, message):
    from agents import web
    from agents.core.routers import _component, multimodal
    calls = []
    history = _error_history([[message, {"exception_message": "PRIVATE-SENTINEL"}]])
    original_backend = comfyui.ComfyUIBackend
    monkeypatch.setattr("agents.core.image_generation_runtime.ComfyUIBackend", lambda config:
                        original_backend(config, transport=httpx.MockTransport(
                            lambda req: _service(req, history, calls))))
    catalog_calls = []

    class Catalog:
        def add(self, **kwargs):
            catalog_calls.append(kwargs)
            raise AssertionError("failed generation must not catalog")

    monkeypatch.setattr("agents.core.media_catalog.default_catalog_if_enabled", lambda: Catalog())
    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="owner")
    await composed.worker.tick()
    row = composed.queue.get(task_id)
    assert row.status == "done"
    assert row.result == {
        "status": "failed", "reason": "generation_failed", "tool": "image_generate",
        "result": {"ok": False, "reason": "generation_failed",
                   "provider_response_failed": "comfyui_history_error_v1"},
    }
    assert [req.url.path for req in calls] == ["/prompt", "/history/p-1"]
    assert catalog_calls == []
    assert list((composed.root / "media" / "generated").glob("*.png")) == []
    assert len(list((composed.root / "media" / "image_approvals").glob("*.attempt"))) == 1

    monkeypatch.setattr(multimodal, "get_orch", lambda: composed.orch)
    monkeypatch.setattr(_component, "get_orch", lambda: composed.orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "history-admin")
    app = FastAPI()
    app.include_router(multimodal.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 5000)),
                                 base_url="http://test") as client:
        url = f"/api/media/generation-tasks/{task_id}"
        assert (await client.get(url)).status_code == 401
        response = await client.get(url, headers={"X-Admin-Token": "history-admin"})
    assert response.status_code == 200
    assert response.json() == {
        "task_id": task_id, "state": "failed", "artifact": None,
        "resume_available": False, "enhance_available": False,
    }
    assert "no-store" in response.headers["cache-control"]
    assert "PRIVATE-SENTINEL" not in json.dumps(row.result) + response.text
    assert "comfyui_history_error_v1" not in response.text
    assert "generation_failed" not in response.text

    replay = await composed.coordinator._approved_image_tool_rpc_execute(row)
    assert replay["status"] == "failed" and replay["reason"] == "trusted_execution_required"
    await composed.worker.tick()
    assert len([req for req in calls if req.method == "POST"]) == 1
    assert [req.url.path for req in calls] == ["/prompt", "/history/p-1"]


@pytest.mark.parametrize("case", [
    "wrong_id", "mixed_ids", "error_true", "missing_status", "duplicate_json",
    "poll_timeout", "transport_loss", "guard_same_reason", "publication_failure",
])
@pytest.mark.asyncio
async def test_signed_worker_other_outcomes_remain_uncertain(composed, monkeypatch, case):
    from agents import web
    from agents.core import image_generation_runtime as runtime
    from agents.core.routers import _component, multimodal

    calls = []
    history = {
        "wrong_id": {"p-2": _error_history()["p-1"]},
        "mixed_ids": {"p-1": _error_history()["p-1"], "p-2": _error_history()["p-1"]},
        "error_true": {"p-1": {"status": {
            "status_str": "error", "completed": True, "messages": [],
        }}},
        "missing_status": {"p-1": {"outputs": {}}},
        "poll_timeout": {},
    }.get(case)
    duplicate = (b'{"p-1":{"status":{"status_str":"error","completed":false,"messages":[]}},'
                 b'"p-1":{"status":{"status_str":"error","completed":false,"messages":[]}}}')

    def service(request):
        calls.append(request)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        if request.url.path == "/history/p-1":
            if case == "transport_loss":
                raise httpx.ReadTimeout("PRIVATE-SENTINEL", request=request)
            if case == "duplicate_json":
                return httpx.Response(200, content=duplicate)
            if case in {"publication_failure", "guard_same_reason"}:
                return httpx.Response(200, json=output_history())
            return httpx.Response(200, json=history)
        if request.url.path == "/view" and case in {"publication_failure", "guard_same_reason"}:
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        raise AssertionError(request.url)

    original_backend = comfyui.ComfyUIBackend

    def backend(config):
        if case in {"wrong_id", "poll_timeout"}:
            config = replace(config, timeout=0.04, poll_interval=0.005)
        return original_backend(config, transport=httpx.MockTransport(service))

    monkeypatch.setattr("agents.core.image_generation_runtime.ComfyUIBackend", backend)
    if case == "guard_same_reason":
        original_config = runtime.LocalImageRuntime._config

        def fail_config_after_view(self, options=None):
            if any(req.url.path == "/view" for req in calls):
                raise comfyui.ImageGenerationError("generation_failed")
            return original_config(self, options)

        monkeypatch.setattr(runtime.LocalImageRuntime, "_config", fail_config_after_view)
    if case == "publication_failure":
        def fail_publication(*_args, **_kwargs):
            raise comfyui.ImageGenerationError("artifact_write_failed")

        monkeypatch.setattr(comfyui, "save_artifact", fail_publication)

    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="owner")
    await composed.worker.tick()
    row = composed.queue.get(task_id)
    assert row.status == "done"
    expected_reason = {
        "wrong_id": "generation_timeout_submission_may_continue",
        "poll_timeout": "generation_timeout_submission_may_continue",
        "mixed_ids": "generation_failed",
        "error_true": "generation_failed",
        "missing_status": "generation_failed",
        "guard_same_reason": "generation_failed",
        "duplicate_json": "invalid_response",
        "transport_loss": "backend_unavailable_submission_may_continue",
        "publication_failure": "artifact_write_failed",
    }[case]
    assert row.result["status"] == "failed" and row.result["reason"] == expected_reason
    assert row.result["result"]["reason"] == expected_reason
    assert "provider_response_failed" not in row.result["result"]
    assert "PRIVATE-SENTINEL" not in json.dumps(row.result)
    assert list((composed.root / "media" / "generated").glob("*.png")) == []

    monkeypatch.setattr(multimodal, "get_orch", lambda: composed.orch)
    monkeypatch.setattr(_component, "get_orch", lambda: composed.orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "history-admin")
    app = FastAPI()
    app.include_router(multimodal.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 5000)),
                                 base_url="http://test") as client:
        response = await client.get(f"/api/media/generation-tasks/{task_id}",
                                    headers={"X-Admin-Token": "history-admin"})
    assert response.status_code == 200
    assert response.json() == {
        "task_id": task_id, "state": "uncertain", "artifact": None,
        "resume_available": False, "enhance_available": False,
    }
    assert "no-store" in response.headers["cache-control"]
    assert "PRIVATE-SENTINEL" not in response.text
    assert sum(req.url.path == "/prompt" for req in calls) == 1
    assert sum(req.url.path == "/view" for req in calls) == int(case in {"guard_same_reason", "publication_failure"})
