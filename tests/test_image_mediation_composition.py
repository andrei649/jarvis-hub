"""The image path must use production bridge composition, not a raw-kernel stub."""

import asyncio
import copy
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
from tests.test_local_image_runtime import PNG
from tests.test_task_mediation_evidence import _head_anchor, _signer


@pytest.fixture(params=["off", "enforce"])
def composed(tmp_path, monkeypatch, request):
    from agents.core import image_generation_runtime as image

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_LOCAL_IMAGE_GENERATION", "1")
    monkeypatch.setenv("JARVIS_COMFYUI_CHECKPOINT", "sd-v1.safetensors")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "balanced")
    requests = []

    def service(req):
        requests.append(req)
        if req.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "nerva-reference.png", "subfolder": "", "type": "input"})
        if req.method == "POST":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        if req.url.path.startswith("/history/"):
            return httpx.Response(200, json={"p-1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": "image.png", "subfolder": "", "type": "output"}]}},
            }})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    backend = image.ComfyUIBackend
    monkeypatch.setattr(image, "ComfyUIBackend", lambda config: backend(config, transport=httpx.MockTransport(service)))
    path = tmp_path / "queue.db"
    queue = TaskQueue(str(path), mediation_mode=request.param, mediation_signer=_signer(),
                      mediation_head_anchor=_head_anchor(path), mediation_scope="global").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, intent_log=None,
                           kill_switch=None, capabilities=None, budget_ledger=None,
                           loop_detector=None, permission_gate=None)
    actions = []
    hooks = SimpleNamespace(effect=None)
    kernel = make_action_kernel(orch)

    def observed(action, **kwargs):
        actions.append(action)
        if action.payload.get("effect") == "local_image" and hooks.effect is not None:
            hooks.effect(action)
        return kernel(action, **kwargs)

    # This is the real composition omitted by the initial image-only fixture.
    worker.bind_mediation(observed, _signer())
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register("tool.rpc", coordinator._approved_image_tool_rpc_execute)
    worker.executor = executor.execute
    try:
        yield SimpleNamespace(queue=queue, worker=worker, orch=orch, coordinator=coordinator,
                              executor=executor, requests=requests, actions=actions, root=tmp_path,
                              hooks=hooks, kernel=observed)
    finally:
        queue.close()


async def proposal(rig):
    return await rig.orch.tool_rpc.handle({"tool": "image_generate", "args": {"prompt": "blue boat"}})


@pytest.mark.asyncio
async def test_bound_bridge_accepts_exact_image_proposal_without_execution(composed):
    result = await proposal(composed)
    assert result.get("task_id"), result
    task = composed.queue.get(result["task_id"])
    assert task.status == "blocked"
    assert task.kind == "tool.rpc"
    assert task.payload["tool"] == task.payload["target"] == "image_generate"
    assert composed.requests == []
    if composed.queue.mediation_mode == "enforce":
        assert task.mediation_receipt["kind"] == "tool.rpc"
        assert composed.queue.verified_mediation_stats()["authorized_enqueue"] == 1


@pytest.mark.asyncio
async def test_authenticated_http_proposal_approval_worker_and_artifact(composed, monkeypatch):
    from fastapi import FastAPI

    from agents import web
    from agents.core.routers import _component, autonomy, multimodal

    monkeypatch.setattr(web, "USER_TOKEN", "image-test-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "image-test-admin")
    for module in (autonomy, multimodal, _component):
        monkeypatch.setattr(module, "get_orch", lambda: composed.orch)
    app = FastAPI()
    app.include_router(multimodal.router)
    app.include_router(autonomy.router)
    transport = httpx.ASGITransport(app, client=("198.51.100.2", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        endpoint = "/api/media/generate"
        payload = {"kind": "image", "prompt": "blue boat", "seed": 7}
        assert (await client.post(endpoint, json=payload)).status_code == 401
        response = await client.post(endpoint, json=payload, headers={"X-User-Token": "image-test-user"})
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]
        decision_url = f"/autonomy/tasks/{task_id}/decision"
        assert (await client.post(decision_url, json={"action": "accept"})).status_code == 401
        assert (await client.post(decision_url, json={"action": "accept"},
                                  headers={"X-User-Token": "image-test-user"})).status_code == 401
        assert composed.queue.get(task_id).status == "blocked"
        assert (await composed.worker.tick())["ran"] == 0
        assert composed.requests == []
        response = await client.post(decision_url, json={"action": "accept"},
                                     headers={"X-Admin-Token": "image-test-admin"})
        assert response.status_code == 200, response.text
        assert composed.requests == []
        await composed.worker.tick()
        task = composed.queue.get(task_id)
        assert task.result["status"] == "ok", task.result
        assert task.decided_by == "admin"
        artifact = task.result["result"]["result"]
        assert "path" not in artifact
        assert (await client.get(artifact["url"])).status_code == 401
        response = await client.get(artifact["url"], headers={"X-User-Token": "image-test-user"})
        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers["x-content-type-options"] == "nosniff"
    assert sum(r.method == "POST" for r in composed.requests) == 1
    assert len([a for a in composed.actions if a.payload.get("effect") == "local_image"]) == 1
    if composed.queue.mediation_mode == "enforce":
        stats = composed.queue.verified_mediation_stats()
        assert stats["valid"] and stats["authorized_enqueue"] == stats["governed"] == 1
        assert task.mediation_receipt["kind"] == "tool.rpc"


@pytest.mark.parametrize("origin", ["generated", "manual", "inbound", "recall:untrusted"])
@pytest.mark.asyncio
async def test_exact_origin_survives_bound_intake_and_effect(composed, origin):
    from agents.core.action_origin import bind_action_origin, reset_action_origin
    from agents.core.security.taint import is_untrusted_source

    token = bind_action_origin(origin)
    try:
        task_id = (await proposal(composed))["task_id"]
    finally:
        reset_action_origin(token)
    await composed.worker.apply_decision(task_id, "accept", decided_by="andrei")
    await composed.worker.tick()
    task = composed.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    effect = next(a for a in composed.actions if a.payload.get("effect") == "local_image")
    assert task.origin == effect.origin == origin
    assert bool(effect.payload.get("tainted")) is is_untrusted_source(origin)
    attempt = json.loads(next((composed.root / "media" / "image_approvals").glob("*.attempt")).read_text())
    assert attempt["origin"] == origin
    if is_untrusted_source(origin):
        assert attempt["verdict"] == "queue"


@pytest.mark.parametrize("composed", ["hold"], indirect=True)
@pytest.mark.asyncio
async def test_bound_hold_refuses_without_receipt_or_proposal(composed):
    response = await proposal(composed)
    assert response == {"ok": False, "reason": "enqueue_failed", "tool": "image_generate"}
    assert composed.queue.list() == []
    assert (await composed.worker.tick())["ran"] == 0
    assert composed.requests == []
    assert not (composed.root / "media" / "image_approvals").exists()


@pytest.mark.parametrize("change", ["name", "target", "kind", "title", "args", "origin", "taint", "decision"])
@pytest.mark.asyncio
async def test_image_guard_rejects_changed_row_after_dispatch_guard(composed, change):
    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="andrei")
    handler = composed.coordinator._approved_image_tool_rpc_execute

    async def tamper(task):
        payload = copy.deepcopy(task.payload)
        column, value = "payload", None
        if change == "name":
            payload["tool"] = "echo"
        elif change == "target":
            payload["target"] = "terminal_run"
        elif change == "args":
            payload["args"]["prompt"] = "unapproved prompt"
        elif change == "taint":
            payload["tainted"] = True
        else:
            column = {"kind": "kind", "title": "title", "origin": "origin", "decision": "decision"}[change]
            value = {"kind": "tool.rpc.other", "title": "other request", "origin": "inbound", "decision": "reject"}[change]
        if column == "payload":
            value = json.dumps(payload)
        composed.queue._conn.execute(f"UPDATE tasks SET {column}=? WHERE id=?", (value, task.id))
        composed.queue._conn.commit()
        return await handler(task)

    composed.executor.register("tool.rpc", tamper)
    await composed.worker.tick()
    assert composed.requests == []
    assert composed.queue.get(task_id).result["status"] == "failed"


@pytest.mark.parametrize("composed", ["enforce"], indirect=True)
@pytest.mark.parametrize("change", ["receipt", "missing_receipt", "execution", "event", "expired", "policy"])
@pytest.mark.asyncio
async def test_current_receipt_is_revalidated_after_worker_dispatch(composed, change):
    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="andrei")
    handler = composed.coordinator._approved_image_tool_rpc_execute

    async def tamper(task):
        if change == "expired":
            composed.queue._clock_ms = lambda: task.mediation_receipt["expires_at_ms"] + 1
        elif change == "policy":
            composed.queue._mediation_policy_revision = "different-current-policy"
        elif change == "event":
            composed.queue._conn.execute("DELETE FROM task_mediation_events WHERE task_id=? AND outcome='governed'", (task.id,))
        elif change == "execution":
            composed.queue._conn.execute("UPDATE tasks SET mediation_execution_id='forged' WHERE id=?", (task.id,))
        else:
            receipt = copy.deepcopy(task.mediation_receipt)
            receipt["signature"] = "forged"
            value = json.dumps(receipt) if change == "receipt" else None
            composed.queue._conn.execute("UPDATE tasks SET mediation_receipt=? WHERE id=?", (value, task.id))
        composed.queue._conn.commit()
        result = await handler(task)
        assert result["reason"] == "mediation_execution_required", result
        return result

    composed.executor.register("tool.rpc", tamper)
    await composed.worker.tick()
    assert composed.requests == []


@pytest.mark.parametrize("change", ["revoked", "kill_switch", "receipt"])
@pytest.mark.asyncio
async def test_final_guard_refuses_authority_change_during_kernel_recheck(composed, change):
    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="andrei")

    def effect(_action):
        if change == "kill_switch":
            raise RuntimeError("kernel unavailable")
        if change == "receipt" and composed.queue.mediation_mode == "enforce":
            composed.queue._conn.execute("UPDATE tasks SET mediation_receipt=NULL WHERE id=?", (task_id,))
        else:
            composed.queue._conn.execute("UPDATE tasks SET decision='reject' WHERE id=?", (task_id,))
        composed.queue._conn.commit()

    composed.hooks.effect = effect
    await composed.worker.tick()
    assert composed.requests == []
    assert not list((composed.root / "media" / "image_approvals").glob("*.attempt"))


@pytest.mark.asyncio
async def test_forged_canonical_payload_cannot_dispatch_other_tools(composed):
    task = SimpleNamespace(kind="tool.rpc", payload={"tool": "echo", "target": "echo", "args": {}})
    for kind, tool, target in [("tool.rpc", "echo", "echo"), ("tool.rpc.other", "image_generate", "image_generate"),
                               ("tool.rpc", "image_generate", "echo")]:
        task.kind, task.payload["tool"], task.payload["target"] = kind, tool, target
        result = await composed.coordinator._approved_image_tool_rpc_execute(task)
        assert result == {"status": "failed", "reason": "image_task_required"}
    assert composed.requests == []


@pytest.mark.asyncio
async def test_worker_race_and_rebuilt_runtime_cannot_reuse_one_approval(composed):
    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="andrei")
    await asyncio.gather(composed.worker.tick(), composed.worker.tick())
    task = composed.queue.get(task_id)
    assert task.result["status"] == "ok", task.result
    composed.coordinator._wire_agent_tool_runtime(action_kernel=composed.worker.kernel_gate)
    composed.executor.register("tool.rpc", composed.coordinator._approved_image_tool_rpc_execute)
    assert (await composed.orch.tool_rpc.execute(task))["status"] == "failed"
    assert (await composed.executor.execute(task))["status"] in {"failed", "refused"}
    await composed.worker.tick()
    assert sum(r.method == "POST" for r in composed.requests) == 1


@pytest.mark.parametrize("failure", ["deny", "missing", "exception"])
@pytest.mark.asyncio
async def test_initial_kernel_refusal_never_registers_a_proposal(composed, failure):
    from agents.core.kernel import Decision, Verdict

    def refuse(action, **kwargs):
        if failure == "exception":
            raise RuntimeError("kernel unavailable")
        return Decision(Verdict.DENY, reason="halted", tier=3) if failure == "deny" else None

    composed.worker.bind_mediation(refuse, _signer())
    composed.coordinator._wire_agent_tool_runtime(action_kernel=composed.worker.kernel_gate)
    response = await proposal(composed)
    assert "task_id" not in response and response["ok"] is False
    assert composed.queue.list() == []
    assert not (composed.root / "media" / "image_approvals").exists()
    assert composed.requests == []


@pytest.mark.parametrize("change", ["title", "payload", "origin", "kind"])
@pytest.mark.asyncio
async def test_finalized_intake_mismatch_still_fails_at_existing_bridge(composed, change):
    runtime = composed.orch.tool_rpc._tools["image_generate"]["gated_intake"].__self__
    governed = runtime._enqueue

    def mismatched(agent, kind, title, **kwargs):
        if change == "title":
            title = "unapproved title"
        elif change == "payload":
            kwargs["payload"] = copy.deepcopy(kwargs["payload"])
            kwargs["payload"]["args"]["prompt"] = "unapproved boat"
        elif change == "origin":
            kwargs["origin"] = "inbound"
        else:
            kind = "toolrpc.image_generate"
        return governed(agent, kind, title, **kwargs)

    runtime._enqueue = mismatched
    assert (await proposal(composed))["reason"] == "enqueue_failed"
    assert composed.queue.list() == []
    assert composed.requests == []
    assert not (composed.root / "media" / "image_approvals").exists()


@pytest.mark.asyncio
async def test_public_execute_cannot_borrow_running_approved_row(composed):
    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="andrei")
    handler = composed.coordinator._approved_image_tool_rpc_execute

    async def public_first(task):
        for context in (None, object()):
            denied = await composed.orch.tool_rpc.execute(task, execution_context=context)
            assert denied["status"] == "failed"
        assert composed.requests == []
        return await handler(task)

    composed.executor.register("tool.rpc", public_first)
    await composed.worker.tick()
    assert composed.queue.get(task_id).result["status"] == "ok"
    assert sum(r.method == "POST" for r in composed.requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
@pytest.mark.asyncio
async def test_ambiguous_post_cannot_replay_after_queue_and_runtime_restart(composed, monkeypatch, failure):
    from agents.core import image_generation_runtime as image
    from agents.core.media_backends.comfyui import ComfyUIBackend

    submitted = asyncio.Event()
    calls = []

    async def service(request):
        calls.append(request)
        submitted.set()
        if failure == "timeout":
            raise httpx.ReadTimeout("unknown submission result", request=request)
        await asyncio.Event().wait()

    monkeypatch.setattr(image, "ComfyUIBackend", lambda config: ComfyUIBackend(config, transport=httpx.MockTransport(service)))
    task_id = (await proposal(composed))["task_id"]
    await composed.worker.apply_decision(task_id, "accept", decided_by="andrei")
    running = asyncio.create_task(composed.worker.tick())
    await asyncio.wait_for(submitted.wait(), timeout=2)
    if failure == "cancel":
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    else:
        await running
        assert composed.queue.get(task_id).result["reason"] == "submission_unknown"
    attempt = next((composed.root / "media" / "image_approvals").glob("*.attempt"))
    before = attempt.read_bytes()
    mode = composed.queue.mediation_mode
    composed.queue.close()
    path = composed.root / "queue.db"
    reopened = TaskQueue(str(path), mediation_mode=mode, mediation_signer=_signer(),
                         mediation_head_anchor=_head_anchor(path), mediation_scope="global").initialize()
    try:
        composed.orch.autonomy_queue = reopened
        worker = AutonomyWorker(reopened, policy=AutonomyPolicy())
        composed.orch.autonomy = worker
        worker.bind_mediation(composed.kernel, _signer())
        composed.coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
        executor = TaskExecutor(execution_guard=worker.execution_allowed)
        executor.register("tool.rpc", composed.coordinator._approved_image_tool_rpc_execute)
        worker.executor = executor.execute
        assert (await executor.execute(reopened.get(task_id)))["status"] in {"failed", "refused"}
        await worker.tick()
        assert attempt.read_bytes() == before
        assert len(calls) == 1 and calls[0].method == "POST"
    finally:
        reopened.close()
