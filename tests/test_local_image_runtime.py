"""Real queue/worker and kernel approval path; only ComfyUI HTTP is simulated."""
import asyncio
import base64
import copy
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.kernel.binding import make_action_kernel

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    module = importlib.import_module("agents.core.image_generation_runtime")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_LOCAL_IMAGE_GENERATION", "1")
    monkeypatch.setenv("JARVIS_COMFYUI_CHECKPOINT", "sd-v1.safetensors")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "balanced")
    requests = []

    def service(request):
        requests.append(request)
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "nerva-reference.png", "subfolder": "", "type": "input"})
        if request.method == "POST":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        if request.url.path.startswith("/history/"):
            return httpx.Response(200, json={"p-1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": "nerva_1.png", "subfolder": "", "type": "output"}]}},
            }})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    backend = module.ComfyUIBackend
    monkeypatch.setattr(module, "ComfyUIBackend", lambda config: backend(config, transport=httpx.MockTransport(service)))
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, intent_log=None,
                           kill_switch=None, budget_ledger=None, loop_detector=None, permission_gate=None)
    from agents.core.routers import _component
    monkeypatch.setattr(_component, "get_orch", lambda: orch)
    kernel = make_action_kernel(orch)
    actions = []

    def observed(action, **kwargs):
        actions.append(action)
        return kernel(action, **kwargs)

    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=observed)
    executor = TaskExecutor().register("tool.rpc", coordinator._approved_image_tool_rpc_execute)
    worker.executor = executor.execute
    value = SimpleNamespace(module=module, queue=queue, worker=worker, orch=orch, coordinator=coordinator,
                            requests=requests, actions=actions, root=tmp_path)
    yield value
    queue.close()


async def propose(rig, **args):
    return await rig.orch.tool_rpc.handle({"tool": "image_generate", "args": {"prompt": "blue boat", **args}})


@pytest.mark.asyncio
async def test_real_worker_requires_exact_human_approval_and_rechecks_kernel(rig):
    proposal = await propose(rig)
    task_id = proposal["task_id"]
    assert rig.requests == []
    assert rig.queue.get(task_id).status == "blocked"
    early = await rig.coordinator._approved_image_tool_rpc_execute(rig.queue.get(task_id))
    assert early["status"] == "failed"
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    assert rig.requests == []
    await rig.worker.tick()
    result = rig.queue.get(task_id).result
    assert result["status"] == "ok", result
    artifact = result["result"]["result"]
    assert artifact["url"].startswith("/api/media/generated/")
    assert "path" not in artifact
    assert sum(r.method == "POST" for r in rig.requests) == 1
    effects = [a for a in rig.actions if a.payload.get("effect") == "local_image"]
    assert len(effects) == 1
    assert effects[0].payload["risk_tier"] >= rig.queue.get(task_id).risk_tier
    assert len(list((rig.root / "media" / "image_approvals").glob("*.attempt"))) == 1


@pytest.mark.asyncio
async def test_inbound_origin_and_taint_survive_real_worker(rig):
    from agents.core.action_origin import bind_action_origin, reset_action_origin
    token = bind_action_origin("inbound")
    try:
        task_id = (await propose(rig))["task_id"]
    finally:
        reset_action_origin(token)
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(task_id).result
    assert result["status"] == "ok", result
    effect = next(a for a in rig.actions if a.payload.get("effect") == "local_image")
    assert effect.origin == "inbound"
    assert effect.payload["tainted"] is True
    receipt = json.loads(next((rig.root / "media" / "image_approvals").glob("*.attempt")).read_text())
    assert receipt["verdict"] == "queue"


@pytest.mark.parametrize("change", ["prompt", "backend", "origin", "tier", "policy", "kernel_off", "disabled"])
@pytest.mark.asyncio
async def test_approval_cannot_authorize_changed_payload_backend_or_authority(rig, monkeypatch, change):
    task_id = (await propose(rig))["task_id"]
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    if change == "prompt":
        payload = copy.deepcopy(rig.queue.get(task_id).payload)
        payload["args"]["prompt"] = "different unapproved boat"
        rig.queue._conn.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(payload), task_id))
    elif change == "origin":
        rig.queue._conn.execute("UPDATE tasks SET origin='manual' WHERE id=?", (task_id,))
    elif change == "tier":
        rig.queue._conn.execute("UPDATE tasks SET risk_tier=1 WHERE id=?", (task_id,))
    elif change == "policy":
        rig.queue._conn.execute("UPDATE tasks SET decided_by='policy' WHERE id=?", (task_id,))
    elif change == "backend":
        monkeypatch.setenv("JARVIS_COMFYUI_CHECKPOINT", "other.safetensors")
    elif change == "kernel_off":
        monkeypatch.delenv("JARVIS_ACTION_KERNEL")
    elif change == "disabled":
        monkeypatch.delenv("JARVIS_LOCAL_IMAGE_GENERATION")
    rig.queue._conn.commit()
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(task_id).result["status"] == "failed"


@pytest.mark.asyncio
async def test_model_cannot_supply_approval_binding_or_endpoint(rig):
    for args in ({"_binding": "fake"}, {"url": "http://evil.example"}, {"approved": True}, {"task_id": 1}):
        result = await propose(rig, **args)
        assert result["ok"] is False
        assert "task_id" not in result
    assert rig.requests == []


@pytest.mark.asyncio
async def test_one_approval_is_consumed_concurrently_and_across_runtime_restart(rig):
    task_id = (await propose(rig))["task_id"]
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    rig.queue.transition(task_id, "running")
    task = rig.queue.get(task_id)
    results = await asyncio.gather(*(rig.coordinator._approved_image_tool_rpc_execute(task) for _ in range(2)))
    assert sum(r["status"] == "ok" for r in results) == 1, results
    rig.coordinator._wire_agent_tool_runtime(action_kernel=make_action_kernel(rig.orch))
    replay = await rig.coordinator._approved_image_tool_rpc_execute(task)
    assert replay["status"] == "failed"
    assert sum(r.method == "POST" for r in rig.requests) == 1


@pytest.mark.asyncio
async def test_media_route_only_proposes_then_guarded_artifact_route_returns_bytes(rig, monkeypatch):
    from fastapi import FastAPI

    from agents.core.routers import multimodal
    app = FastAPI()
    app.include_router(multimodal.router)
    monkeypatch.setattr(multimodal, "get_orch", lambda: rig.orch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        status = (await client.get("/api/media")).json()
        assert status["local_image"]["configured"] is True
        assert status["local_image"]["reachable"] is None
        proposed = await client.post("/api/media/generate", json={"kind": "image", "prompt": "blue boat"})
        assert proposed.status_code == 202
        task_id = proposed.json()["task_id"]
        assert rig.requests == []
        await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
        await rig.worker.tick()
        url = rig.queue.get(task_id).result["result"]["result"]["url"]
        response = await client.get(url)
        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers["x-content-type-options"] == "nosniff"
        assert (await client.get("/api/media/generated/not-a-valid-id")).status_code == 404
        assert (await client.get("/api/media/generated/" + "a" * 32)).status_code == 404
        assert (await client.post("/api/media/generate", json={"kind": "image", "prompt": "boat", "approved": True})).status_code == 422


@pytest.mark.parametrize("verdict", ["deny", "invalid", "exception"])
@pytest.mark.asyncio
async def test_execution_kernel_failures_refuse_before_any_post(rig, verdict):
    from agents.core.kernel import Decision, Verdict
    task_id = (await propose(rig))["task_id"]
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    def broken(action, **kwargs):
        if action.payload.get("effect") != "local_image":
            return Decision(Verdict.QUEUE, reason="approval", tier=3)
        if verdict == "exception":
            raise RuntimeError("kernel unavailable")
        return Decision(Verdict.DENY, reason="halted", tier=3) if verdict == "deny" else None
    rig.coordinator._wire_agent_tool_runtime(action_kernel=broken)
    rig.worker.executor = TaskExecutor().register("tool.rpc", rig.coordinator._approved_image_tool_rpc_execute).execute
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(task_id).result["status"] == "failed"


@pytest.mark.asyncio
async def test_missing_proposal_or_failed_durable_attempt_is_not_permission(rig, monkeypatch):
    task_id = (await propose(rig))["task_id"]
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    def unavailable(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(rig.module, "_write_exclusive", unavailable)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(task_id).result["reason"] == "durable_attempt_unavailable"


@pytest.mark.asyncio
async def test_no_proposal_record_cannot_execute_even_with_accepted_row(rig):
    task_id = (await propose(rig))["task_id"]
    next((rig.root / "media" / "image_approvals").glob("*.proposal")).unlink()
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(task_id).result["status"] == "failed"


@pytest.mark.asyncio
async def test_direct_runtime_does_not_infer_approval_from_args(rig):
    task_id = (await propose(rig))["task_id"]
    runtime = rig.module.LocalImageRuntime(queue=rig.queue, approved_task=lambda: None,
        authorizer=make_action_kernel(rig.orch), enqueue=rig.queue.enqueue)
    result = await runtime.execute(rig.queue.get(task_id).payload["args"])
    assert result == {"ok": False, "reason": "trusted_execution_required"}
    assert rig.requests == []


@pytest.mark.parametrize("mode", ["hold", "enforce"])
@pytest.mark.asyncio
async def test_strict_mediation_without_bound_signer_stays_fail_closed(rig, mode):
    queue = TaskQueue(db_path=str(rig.root / (mode + ".db")), mediation_mode=mode).initialize()
    try:
        worker = AutonomyWorker(queue, policy=AutonomyPolicy())
        orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue)
        coordinator = AutonomyCoordinator(orch)
        coordinator._wire_agent_tool_runtime(action_kernel=make_action_kernel(rig.orch))
        response = await orch.tool_rpc.handle({"tool": "image_generate", "args": {"prompt": "boat"}})
        assert response["ok"] is False
        assert "task_id" not in response
        assert rig.requests == []
        assert queue.mediation_mode == mode
    finally:
        queue.close()


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
@pytest.mark.asyncio
async def test_ambiguous_submission_cannot_replay_after_rebuilding_runtime(rig, monkeypatch, failure):
    from agents.core.media_backends.comfyui import ComfyUIBackend
    submitted = asyncio.Event()
    calls = []
    async def service(request):
        calls.append(request)
        submitted.set()
        if failure == "timeout":
            raise httpx.ReadTimeout("unknown result", request=request)
        await asyncio.Event().wait()
    monkeypatch.setattr(rig.module, "ComfyUIBackend", lambda config: ComfyUIBackend(config, transport=httpx.MockTransport(service)))
    task_id = (await propose(rig))["task_id"]
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    rig.queue.transition(task_id, "running")
    task = rig.queue.get(task_id)
    running = asyncio.create_task(rig.coordinator._approved_image_tool_rpc_execute(task))
    await asyncio.wait_for(submitted.wait(), timeout=2)
    if failure == "cancel":
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    else:
        result = await running
        assert result["reason"] == "submission_unknown"
    rig.coordinator._wire_agent_tool_runtime(action_kernel=make_action_kernel(rig.orch))
    replay = await rig.coordinator._approved_image_tool_rpc_execute(task)
    assert replay["reason"] == "approval_consumed_result_may_be_unknown"
    assert len(calls) == 1 and calls[0].method == "POST"


@pytest.mark.asyncio
async def test_media_endpoints_enforce_real_user_guard_before_read_or_proposal(rig, monkeypatch):
    from fastapi import FastAPI

    from agents import web
    from agents.core.routers import multimodal
    app = FastAPI()
    app.include_router(multimodal.router)
    monkeypatch.setattr(web, "USER_TOKEN", "image-test-token")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.setattr(multimodal, "get_orch", lambda: rig.orch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 5000)), base_url="http://test") as client:
        assert (await client.get("/api/media")).status_code == 401
        assert (await client.get("/api/media/generated/" + "a" * 32)).status_code == 401
        assert (await client.post("/api/media/generate", json={"kind": "image", "prompt": "boat"})).status_code == 401
        assert rig.requests == []
        allowed = await client.get("/api/media", headers={"X-User-Token": "image-test-token"})
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_disabled_image_tool_is_inert_at_proposal(rig, monkeypatch):
    monkeypatch.delenv("JARVIS_LOCAL_IMAGE_GENERATION")
    result = await propose(rig)
    assert result == {"ok": False, "reason": "local_image_disabled", "tool": "image_generate"}
    assert not (rig.root / "media").exists()
    assert rig.requests == []


@pytest.mark.asyncio
async def test_proposal_preserves_inbound_origin_even_before_worker_is_bound(rig):
    from agents.core.action_origin import bind_action_origin, reset_action_origin
    orch = SimpleNamespace(agents={}, autonomy_queue=rig.queue)
    AutonomyCoordinator(orch)._wire_agent_tool_runtime(action_kernel=make_action_kernel(rig.orch))
    token = bind_action_origin("inbound")
    try:
        response = await orch.tool_rpc.handle({"tool": "image_generate", "args": {"prompt": "boat"}})
    finally:
        reset_action_origin(token)
    task = rig.queue.get(response["task_id"])
    assert task.origin == "inbound"
    assert task.payload["tainted"] is True
    assert rig.requests == []


# ── editing an artifact the hub already generated (H515 / H598) ──────────────

def seed_reference(rig, artifact_id="c" * 32):
    """Put a real artifact where a real generation would have left one."""
    root = rig.root / "media" / "generated"
    root.mkdir(parents=True, exist_ok=True)
    (root / (artifact_id + ".png")).write_bytes(PNG)
    return artifact_id


@pytest.mark.asyncio
async def test_an_edit_crosses_the_same_approval_gate_as_a_generation(rig):
    """The reference buys no shortcut: an edit is the identical propose/approve/execute
    tuple, and the transport is untouched until a human has accepted it by name."""
    reference = seed_reference(rig)
    task_id = (await propose(rig, reference=reference, strength=35))["task_id"]
    assert rig.requests == []
    assert rig.queue.get(task_id).status == "blocked"
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    assert rig.requests == []
    await rig.worker.tick()

    result = rig.queue.get(task_id).result
    assert result["status"] == "ok", result
    assert [r.url.path for r in rig.requests if r.method == "POST"] == ["/upload/image", "/prompt"]
    workflow = json.loads(next(r for r in rig.requests if r.url.path == "/prompt").content)["prompt"]
    assert workflow["11"]["class_type"] == "LoadImage"
    assert workflow["3"]["inputs"]["denoise"] == 0.35
    assert "EmptyLatentImage" not in {node["class_type"] for node in workflow.values()}
    artifact = result["result"]["result"]
    assert artifact["artifact_id"] != reference and "path" not in artifact


@pytest.mark.asyncio
async def test_the_approved_reference_is_the_one_that_is_edited(rig):
    """Swapping the reference after approval is the same class of forgery as swapping
    the prompt: the owner accepted an edit *of a particular image*."""
    approved = seed_reference(rig)
    other = seed_reference(rig, "d" * 32)
    task_id = (await propose(rig, reference=approved))["task_id"]
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    payload = copy.deepcopy(rig.queue.get(task_id).payload)
    payload["args"]["reference"] = other
    rig.queue._conn.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(payload), task_id))
    rig.queue._conn.commit()
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(task_id).result["status"] == "failed"


@pytest.mark.asyncio
async def test_a_reference_that_names_nothing_is_refused_before_any_transport(rig):
    task_id = (await propose(rig, reference="e" * 32))["task_id"]
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    await rig.worker.tick()
    result = rig.queue.get(task_id).result
    assert result["status"] == "failed" and result["reason"] == "reference_not_found"
    assert rig.requests == [], "the approval is not spent on a reference we could reject first"


@pytest.mark.asyncio
async def test_an_edit_proposal_refuses_a_canvas_size_at_the_tool_boundary(rig):
    reference = seed_reference(rig)
    refused = await propose(rig, reference=reference, width=768)
    assert refused["ok"] is False
    assert rig.queue.list() == [] and rig.requests == []
