"""Declarative image services through real HTTP, signed intake and execution."""

import asyncio
import base64
import json
import struct
import zlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.kernel.binding import make_action_kernel
from agents.core.routers import _component, autonomy, multimodal
from tests.test_task_mediation_evidence import _head_anchor, _signer


def canvas(width=64, height=128):
    def chunk(kind, body):
        return struct.pack("!I", len(body)) + kind + body + struct.pack(
            "!I", zlib.crc32(kind + body) & 0xFFFFFFFF
        )

    rows = b"".join(b"\0" + bytes((20, 60, 160, 255)) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


PNG = canvas()
OWNER = {"X-User-Token": "provider-user", "X-Admin-Token": "provider-owner"}
BODY = {"kind": "image", "prompt": "blue boat", "backend": "studio", "model": "paint-v1",
        "width": 64, "height": 128}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from agents.core import image_generation_runtime as image
    from agents.core import media_catalog

    config = {"studio": {"protocol": "openai_images", "url": "http://127.0.0.1:8765",
                         "models": ["paint-v1"]}}
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    # Catalog's bootstrap default is captured at import; collection may precede
    # this per-test home. Keep its real store beside the real artifact/gallery root.
    monkeypatch.setattr(media_catalog, "_DEFAULT_FILE", tmp_path / "media" / "catalog.json")
    monkeypatch.setenv("JARVIS_LOCAL_IMAGE_GENERATION", "1")
    monkeypatch.setenv("JARVIS_LOCAL_IMAGE_PROVIDERS", json.dumps(config))
    monkeypatch.setenv("JARVIS_LOCAL_IMAGE_DEFAULT_BACKEND", "studio")
    monkeypatch.delenv("JARVIS_COMFYUI_CHECKPOINT", raising=False)
    monkeypatch.delenv("JARVIS_COMFYUI_BACKENDS", raising=False)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "balanced")
    monkeypatch.setenv("JARVIS_MEDIA_CATALOG", "1")
    monkeypatch.setattr(web, "USER_TOKEN", "provider-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "provider-owner")
    requests = []
    hooks = SimpleNamespace(response=None)

    async def service(request):
        requests.append(request)
        if hooks.response is not None:
            return await hooks.response(request)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    # Only the real image backend's transport is replaced; no policy or runtime fake.
    backend = getattr(image, "LocalOpenAIImageBackend", None)

    def simulated(config):
        assert backend is not None, "local compatible image protocol not implemented"
        return backend(config, transport=httpx.MockTransport(service))

    monkeypatch.setattr(image, "LocalOpenAIImageBackend", simulated, raising=False)
    path = tmp_path / "queue.db"
    queue = TaskQueue(str(path), mediation_mode="enforce", mediation_signer=_signer(),
                      mediation_head_anchor=_head_anchor(path), mediation_scope="global").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, intent_log=None,
                           kill_switch=None, capabilities=None, budget_ledger=None,
                           loop_detector=None, permission_gate=None)
    actions = []
    kernel = make_action_kernel(orch)

    def observed(action, **kwargs):
        actions.append(action)
        return kernel(action, **kwargs)

    worker.bind_mediation(observed, _signer())
    coordinator = AutonomyCoordinator(orch)

    def wire():
        coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
        executor = TaskExecutor(execution_guard=worker.execution_allowed)
        executor.register("tool.rpc", coordinator._approved_image_tool_rpc_execute)
        worker.executor = executor.execute
        return executor

    executor = wire()
    for module in (_component, autonomy, multimodal):
        monkeypatch.setattr(module, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(multimodal.router)
    app.include_router(autonomy.router)
    value = SimpleNamespace(queue=queue, worker=worker, orch=orch, coordinator=coordinator,
                            executor=executor, requests=requests, actions=actions, root=tmp_path,
                            hooks=hooks, config=config, wire=wire, path=path)
    value.client = lambda: httpx.AsyncClient(
        transport=httpx.ASGITransport(app, client=("198.51.100.2", 5000)),
        base_url="http://test", headers=OWNER,
    )
    yield value
    queue.close()


async def propose(rig, client, **changes):
    response = await client.post("/api/media/generate", json={**BODY, **changes})
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    task = rig.queue.get(task_id)
    assert task.status == "blocked" and task.mediation_receipt["kind"] == "tool.rpc"
    assert "seed" not in task.payload["args"]
    assert rig.requests == []
    return task_id


async def accept(client, task_id):
    response = await client.post(f"/autonomy/tasks/{task_id}/decision", json={"action": "accept"})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_registered_default_pure_status_signed_approval_one_post_and_readback(rig):
    async with rig.client() as client:
        status = (await client.get("/api/media")).json()["local_image"]
        assert status["configured"] is True and status["reachable"] is None
        assert status["backend"] == "studio" and status["edit"] is False
        row = next(row for row in status["backends"] if row["id"] == "studio")
        assert row == {"id": "studio", "models": ["paint-v1"], "protocol": "openai_images",
                       "edit": False, "max_references": 0, "upscale": []}
        task_id = await propose(rig, client)
        await rig.worker.tick()
        assert rig.requests == []
        await accept(client, task_id)
        assert rig.requests == []
        await rig.worker.tick()
        state = (await client.get(f"/api/media/generation-tasks/{task_id}")).json()
        assert state["state"] == "ready", state
        artifact = state["artifact"]
        assert artifact["bytes"] == len(PNG)
        assert "path" not in artifact and "url" not in artifact
        response = await client.get("/api/media/generated/" + artifact["id"])
        assert response.status_code == 200 and response.content == PNG
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-store"
        gallery = (await client.get("/api/media/catalog")).json()
        (entry,) = gallery["items"]
        assert entry["backend"] == "studio" and entry["prompt"] == "blue boat"
        assert entry["available"] is True and entry["size"] == len(PNG)
        assert "path" not in entry and "url" not in entry
        assert len(rig.requests) == 1
        request = rig.requests[0]
        assert request.method == "POST" and str(request.url) == "http://127.0.0.1:8765/v1/images/generations"
        assert "authorization" not in request.headers
        assert json.loads(request.content) == {"model": "paint-v1", "prompt": "blue boat",
                                              "size": "64x128", "n": 1, "response_format": "b64_json"}
        assert rig.queue.verified_mediation_stats()["valid"] is True
        await rig.worker.tick()
        assert len(rig.requests) == 1


@pytest.mark.parametrize("change", ["endpoint", "model", "disabled", "revoked"])
@pytest.mark.asyncio
async def test_reviewed_provider_changes_or_rejection_cannot_send(rig, monkeypatch, change):
    async with rig.client() as client:
        task_id = await propose(rig, client)
        if change == "revoked":
            response = await client.post(f"/autonomy/tasks/{task_id}/decision", json={"action": "reject"})
            assert response.status_code == 200
        else:
            await accept(client, task_id)
            if change == "disabled":
                monkeypatch.setenv("JARVIS_LOCAL_IMAGE_GENERATION", "0")
            else:
                rig.config["studio"]["url" if change == "endpoint" else "models"] = (
                    "http://127.0.0.1:8766" if change == "endpoint" else ["paint-v2"]
                )
                monkeypatch.setenv("JARVIS_LOCAL_IMAGE_PROVIDERS", json.dumps(rig.config))
        await rig.worker.tick()
        assert rig.requests == []
        state = (await client.get(f"/api/media/generation-tasks/{task_id}")).json()
        assert state["state"] != "ready" and state["artifact"] is None


@pytest.mark.asyncio
async def test_configuration_revoked_while_response_waits_prevents_publication(rig, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    rig.hooks.response = delayed
    async with rig.client() as client:
        task_id = await propose(rig, client)
        await accept(client, task_id)
        running = asyncio.create_task(rig.worker.tick())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            monkeypatch.setenv("JARVIS_LOCAL_IMAGE_GENERATION", "0")
        finally:
            release.set()
            await running
        assert len(rig.requests) == 1
        state = (await client.get(f"/api/media/generation-tasks/{task_id}")).json()
        assert state["state"] != "ready" and state["artifact"] is None
        assert list(rig.root.rglob("*.png")) == []
    # Round 4, item 3: generated, then withheld — its own reason, the gate in detail.
    result = rig.queue.get(task_id).result
    assert (result["reason"], result["detail"]) == ("withheld_after_generation", "local_image_disabled")
    assert _outcomes(rig.queue) == (0, 0)


@pytest.mark.asyncio
async def test_one_approval_survives_restart_without_duplicate_dispatch(rig):
    async with rig.client() as client:
        task_id = await propose(rig, client)
        await accept(client, task_id)
        # Restart durable queue and production composition before executing approval.
        rig.queue.close()
        reopened = TaskQueue(
            str(rig.path), mediation_mode="enforce", mediation_signer=_signer(),
            mediation_head_anchor=_head_anchor(rig.path), mediation_scope="global",
        ).initialize()
        try:
            rig.orch.autonomy_queue = reopened
            worker = AutonomyWorker(reopened, policy=AutonomyPolicy())
            rig.orch.autonomy = worker
            worker.bind_mediation(make_action_kernel(rig.orch), _signer())
            coordinator = AutonomyCoordinator(rig.orch)
            coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
            executor = TaskExecutor(execution_guard=worker.execution_allowed)
            executor.register("tool.rpc", coordinator._approved_image_tool_rpc_execute)
            worker.executor = executor.execute
            await asyncio.gather(worker.tick(), worker.tick())
            task = reopened.get(task_id)
            assert task.result["status"] == "ok", task.result
            artifact = task.result["result"]["result"]
            assert (await client.get(artifact["url"])).content == PNG
            attempt = next((rig.root / "media" / "image_approvals").glob("*.attempt"))
            before = attempt.read_bytes()
            coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
            assert (await coordinator._approved_image_tool_rpc_execute(task))["status"] == "failed"
            await worker.tick()
            assert attempt.read_bytes() == before and len(rig.requests) == 1
        finally:
            reopened.close()


@pytest.mark.parametrize("invalid", ["url", "duplicate", "wrong_canvas"])
@pytest.mark.asyncio
async def test_bad_response_consumes_one_attempt_and_restart_cannot_retry(rig, invalid):
    async def malformed(request):
        if invalid == "url":
            return httpx.Response(200, json={"data": [{"url": "http://127.0.0.1:8765/output.png"}]})
        if invalid == "duplicate":
            return httpx.Response(200, content=b'{"data":[],"data":[]}', headers={"content-type": "application/json"})
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(canvas(64, 64)).decode()}]})

    rig.hooks.response = malformed
    async with rig.client() as client:
        task_id = await propose(rig, client)
        await accept(client, task_id)
        await rig.worker.tick()
        assert rig.queue.get(task_id).result["status"] == "failed"
        attempt = next((rig.root / "media" / "image_approvals").glob("*.attempt"))
        before = attempt.read_bytes()
        rig.wire()
        assert (await rig.coordinator._approved_image_tool_rpc_execute(rig.queue.get(task_id)))["status"] == "failed"
        await rig.worker.tick()
        assert len(rig.requests) == 1 and attempt.read_bytes() == before
        assert list(rig.root.rglob("*.png")) == []
    # A generation that broke is a failure (the contrast to the withheld class below).
    assert _outcomes(rig.queue) == (0, 1)


@pytest.mark.parametrize("option", [{"seed": 7}, {"steps": 5}, {"reference": "a" * 32},
                                    {"references": ["a" * 32]}, {"strength": 40}, {"upscale": 2}])
@pytest.mark.asyncio
async def test_supported_protocol_does_not_silently_drop_unsupported_options(rig, option):
    async with rig.client() as client:
        response = await client.post("/api/media/generate", json={**BODY, **option})
        assert response.status_code == 422, response.text
        assert rig.queue.list() == [] and rig.requests == []


# ── round 4, item 3: generated, then withheld by the post-request guard ───────


def _outcomes(queue):
    stats = queue.capability_outcome_stats("action:tool.rpc")
    return stats["successes"], stats["failures"]


def _deny_local_image(rig, *, then=None):
    """The worker's kernel, except that the runtime's own local-image check is denied
    (or, with *then*, runs *then* and passes)."""
    from dataclasses import replace

    from agents.core.kernel import Verdict

    real = rig.worker._mediation_kernel

    def kernel(action, **kwargs):
        decision = real(action, **kwargs)
        if action.kind == "tool.rpc" and (action.payload or {}).get("effect") == "local_image":
            if then is None:
                return replace(decision, verdict=Verdict.DENY, reason="policy changed")
            then()
        return decision

    rig.worker._mediation_kernel = kernel


@pytest.mark.parametrize("cause", ["kernel_denied", "mediation_execution_required",
                                   "backend_binding_changed", "approved_payload_changed"])
@pytest.mark.asyncio
async def test_an_image_withheld_after_generation_is_its_own_reason_and_records_nothing(
        rig, monkeypatch, cause):
    """Closure A: the backend POST completed and returned an image; then the runtime's
    post-request guard (the recheck after the response, the save_artifact guard)
    withheld it. That is not a refusal (the capability ran) and not a failure (it
    worked; governance withheld the result): ``withheld_after_generation``, the cause in
    ``detail``, nothing recorded. Nothing is published."""
    from dataclasses import fields

    from agents.core import image_generation_runtime as image

    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    def change(task_id):
        if cause == "kernel_denied":
            _deny_local_image(rig)
        elif cause == "mediation_execution_required":
            rig.queue.mediation_mode = "hold"
        elif cause == "backend_binding_changed":
            # The live config differs while the approved head does not: an unequal
            # config (another class) with the very same fields, so the same fingerprint.
            real_config = image.LocalImageRuntime._config

            def drifted(self, options=None):
                config = real_config(self, options)
                drifted_type = type("Drifted", (type(config),), {})
                return drifted_type(**{f.name: getattr(config, f.name) for f in fields(config)})

            monkeypatch.setattr(image.LocalImageRuntime, "_config", drifted)
        else:
            # The durable proposal record changed on disk.
            (proposal,) = (rig.root / "media" / "image_approvals").glob(f"{task_id}-*.proposal")
            proposal.write_text(json.dumps({"digest": "0" * 64}), encoding="utf-8")

    rig.hooks.response = delayed
    async with rig.client() as client:
        task_id = await propose(rig, client)
        await accept(client, task_id)
        running = asyncio.create_task(rig.worker.tick())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            change(task_id)
        finally:
            release.set()
            await running
    task = rig.queue.get(task_id)
    assert len(rig.requests) == 1                       # the image was generated
    assert task.result["status"] == "failed"
    assert task.result["reason"] == "withheld_after_generation", task.result
    assert task.result["detail"] == cause
    assert list(rig.root.rglob("*.png")) == []
    assert _outcomes(rig.queue) == (0, 0)


@pytest.mark.parametrize("cause", ["kernel_denied", "mediation_execution_required"])
@pytest.mark.asyncio
async def test_a_governance_gate_before_the_request_stays_a_refusal(rig, cause):
    """Before any request, ``kernel_denied`` and ``mediation_execution_required`` are
    refusals: nothing reached the backend, nothing is recorded."""
    async with rig.client() as client:
        task_id = await propose(rig, client)
        await accept(client, task_id)

        def hold():
            rig.queue.mediation_mode = "hold"   # the re-check right after the kernel refuses

        _deny_local_image(rig, then=None if cause == "kernel_denied" else hold)
        await rig.worker.tick()
    task = rig.queue.get(task_id)
    assert rig.requests == []
    assert task.result["status"] == "failed" and task.result["reason"] == cause, task.result
    assert _outcomes(rig.queue) == (0, 0)


@pytest.mark.parametrize("gate, env", [
    ("local_image_disabled", {"JARVIS_LOCAL_IMAGE_GENERATION": "0"}),
    ("heavy_features_paused", {"JARVIS_SYSTEM_PROFILE": "gaming"}),
    ("kernel_required", {"JARVIS_ACTION_KERNEL": "0"}),
])
@pytest.mark.asyncio
async def test_a_runtime_gate_before_the_request_is_a_refusal(rig, monkeypatch, gate, env):
    """Round 4, item 3: once a gate re-checked after the request reports
    ``withheld_after_generation``, the runtime's own gates can only be reported before
    the request — refusals: nothing reached the backend, nothing is recorded."""
    async with rig.client() as client:
        task_id = await propose(rig, client)
        await accept(client, task_id)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        await rig.worker.tick()
    task = rig.queue.get(task_id)
    assert rig.requests == []
    assert task.result["status"] == "failed" and task.result["reason"] == gate, task.result
    assert _outcomes(rig.queue) == (0, 0)
