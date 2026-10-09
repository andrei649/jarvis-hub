"""Cloud image flow uses signed real tasks and injected HTTP only."""

import base64
import io

import pytest
from PIL import Image


def png(size=(1024, 1024)):
    out = io.BytesIO()
    Image.new("RGB", size, "blue").save(out, format="PNG")
    return out.getvalue()


def test_fixed_cloud_request_and_manifest():
    from agents.core.media_backends.openai_image import normalize_request
    from agents.core.plugin_gate import BUILTIN_PLUGINS, NetworkAccess

    assert normalize_request("blue square", {}) == {
        "model": "gpt-image-1.5",
        "prompt": "blue square",
        "n": 1,
        "size": "1024x1024",
        "quality": "low",
        "output_format": "png",
        "stream": False,
    }
    manifest = BUILTIN_PLUGINS["cloud-image"]
    assert manifest.network_access is NetworkAccess.RESTRICTED
    assert manifest.allowed_domains == ["api.openai.com"]


@pytest.mark.parametrize(
    "options",
    [
        {"steps": 2},
        {"seed": 1},
        {"reference": "a" * 32},
        {"model": "unapproved"},
        {"size": "auto"},
        {"size": []},
        {"quality": {}},
        {"quality": "auto"},
        {"n": 2},
        {"endpoint": "https://other.test"},
    ],
)
def test_unsupported_cloud_options_refused(options):
    from agents.core.media_backends.openai_image import normalize_request

    with pytest.raises(ValueError):
        normalize_request("test", options)


def test_cloud_result_validates_full_raster_and_discards_metadata():
    from agents.core.media_backends.openai_image import decode_result

    metadata_image = io.BytesIO()
    exif = Image.Exif()
    exif[270] = "untrusted provider metadata"
    Image.new("RGB", (1024, 1024), "blue").save(metadata_image, format="PNG", exif=exif)
    value = {"data": [{"b64_json": base64.b64encode(metadata_image.getvalue()).decode()}]}
    data = decode_result(value, "1024x1024")
    assert not Image.open(io.BytesIO(data)).info
    assert Image.open(io.BytesIO(data)).size == (1024, 1024)
    for invalid in (
        {"data": []},
        {"data": [{"url": "https://other.test"}]},
        {"data": [{"b64_json": "not base64"}]},
        {"data": [{"b64_json": base64.b64encode(png()[:-5]).decode()}]},
    ):
        with pytest.raises(ValueError):
            decode_result(invalid, "1024x1024")
    with pytest.raises(ValueError):
        decode_result(value, "1536x1024")


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import httpx

    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.cloud_image_runtime import CloudImageRuntime
    from agents.core.kernel.binding import make_action_kernel
    from tests.test_task_mediation_evidence import _head_anchor, _signer

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_MEDIA_CATALOG", "1")
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "balanced")
    path = tmp_path / "queue.db"
    queue = TaskQueue(
        str(path),
        mediation_mode="enforce",
        mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(path),
        mediation_scope="global",
    ).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(
        autonomy=worker,
        kill_switch=None,
        capabilities=None,
        intent_log=None,
        budget_ledger=None,
        loop_detector=None,
    )
    kernel = make_action_kernel(orch)
    worker.bind_mediation(kernel, _signer())
    requests = []
    state = SimpleNamespace(
        key="fixture-credential",
        response=lambda: httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]}
        ),
    )

    def transport(req):
        requests.append(req)
        return state.response()

    runtime = CloudImageRuntime(
        worker,
        kernel=kernel,
        redact=lambda s: s.replace(state.key, "[redacted]"),
        root=tmp_path,
        key=lambda: state.key,
        resolver=lambda *a, **kw: (["93.184.216.34"], None),
        transport_factory=lambda target: httpx.MockTransport(transport),
    )
    executor = TaskExecutor(execution_guard=runtime.guard)
    executor.register("plugin.egress", runtime.execute)
    worker.executor = executor.execute
    yield SimpleNamespace(
        runtime=runtime,
        worker=worker,
        queue=queue,
        executor=executor,
        requests=requests,
        state=state,
        root=tmp_path,
        kernel=kernel,
    )
    queue.close()


async def finish(cloud):
    task_id = cloud.runtime.submit("blue square", {}, "user")
    assert cloud.queue.get(task_id).status == "blocked"
    assert not cloud.requests
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    return cloud.queue.get(task_id)


@pytest.mark.asyncio
async def test_signed_cloud_completion_catalog_and_no_replay(cloud):
    from agents.core.media_library import gallery_page, read_catalog_blob

    task = await finish(cloud)
    assert task.result["status"] == "ok", task.result
    assert len(cloud.requests) == 1
    assert cloud.requests[0].headers["authorization"] == "Bearer fixture-credential"
    assert "cookie" not in cloud.requests[0].headers
    rows = gallery_page(cloud.root, generated=True)["items"]
    assert len(rows) == 1 and rows[0]["cloud"] is True and rows[0]["available"] is True
    meta, data = read_catalog_blob(rows[0]["id"], cloud.root)
    assert meta["mime"] == "image/png" and data.startswith(b"\x89PNG")
    assert meta["digest_status"] == "verified"
    from agents.core.media_catalog import MediaCatalog
    catalog_row = MediaCatalog(cloud.root / "media" / "catalog.json").get(rows[0]["id"])
    assert catalog_row["sha256"] == meta["sha256"]
    assert catalog_row["meta"]["sha256"] == meta["sha256"]
    from pathlib import Path

    from agents.core.artifact_store import sniff

    changed = io.BytesIO()
    Image.new("RGB", (1024, 1024), "red").save(changed, format="PNG")
    assert sniff(changed.getvalue()) == "image/png"
    Path(catalog_row["path"]).write_bytes(changed.getvalue())
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(rows[0]["id"], cloud.root)
    assert (await cloud.runtime.execute(task))["status"] == "refused"
    assert len(cloud.requests) == 1
    assert "fixture-credential" not in str(task.result) + str(task.payload)


@pytest.mark.asyncio
async def test_cloud_configuration_rotation_before_approval_refuses(cloud):
    task_id = cloud.runtime.submit("test", {}, "user")
    cloud.state.key = "changed"
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    assert not cloud.requests


@pytest.mark.asyncio
async def test_cloud_ambiguous_post_cannot_repeat(cloud):
    import httpx

    def lost():
        raise httpx.ReadError("fixture-credential")

    cloud.state.response = lost
    task = await finish(cloud)
    assert task.result["status"] == "unknown", task.result
    assert len(cloud.requests) == 1 and "fixture-credential" not in str(task.result)
    assert (await cloud.runtime.execute(task))["status"] == "refused"
    assert len(cloud.requests) == 1


@pytest.mark.asyncio
async def test_restart_finalization_is_idempotent_and_exportable(cloud, monkeypatch):
    from agents.core.media_catalog import MediaCatalog

    original = MediaCatalog.add
    monkeypatch.setattr(
        MediaCatalog, "add", lambda *a, **k: (_ for _ in ()).throw(OSError("unavailable"))
    )
    task = await finish(cloud)
    # Review round 6, item 3: the image and its completion record are durable; only the
    # catalog row failed — a success with a warning (it was ``unknown``).
    assert task.result["status"] == "ok" and len(cloud.requests) == 1
    assert task.result["warning"] == "catalog_record_failed"
    monkeypatch.setattr(MediaCatalog, "add", original)
    result = cloud.runtime.recover(task)
    assert result["status"] == "ok"
    assert cloud.runtime.recover(task) == result
    catalog = MediaCatalog(cloud.root / "media" / "catalog.json")
    assert len(catalog.all()) == 1
    catalog.remove(result["result"]["catalog_id"])
    cloud.runtime.recover(task)
    assert catalog.all() == [], "status reads must not resurrect intentionally removed catalog rows"
    assert len(cloud.requests) == 1


@pytest.mark.asyncio
async def test_stop_while_provider_awaited_prevents_artifact_publication(cloud, monkeypatch):
    from agents.core import estop

    original = cloud.state.response

    def stopped():
        monkeypatch.setattr(estop, "is_engaged", lambda: True)
        return original()

    cloud.state.response = stopped
    task = await finish(cloud)
    # Review round 5, item 8: the stop engaged after the image was generated is a
    # governance withhold (it was "unknown", recorded as a success): nothing published,
    # nothing recorded.
    assert task.result == {"status": "failed", "reason": "withheld_after_generation",
                           "detail": "estop_engaged"}
    assert not list((cloud.root / "media" / "generated").glob("*.png"))
    assert _outcomes(cloud) == (0, 0)


@pytest.mark.asyncio
async def test_cloud_explicit_policy_actor_not_human_authority(cloud):
    task_id = cloud.runtime.submit("test", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="policy")
    await cloud.worker.tick()
    assert not cloud.requests


@pytest.mark.asyncio
async def test_actual_media_route_worker_gallery_and_export(cloud, monkeypatch):
    import zipfile
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setenv("JARVIS_HOME", str(cloud.root))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-token")
    monkeypatch.setattr(web, "USER_TOKEN", "user-token")
    monkeypatch.setattr(
        web, "orch", SimpleNamespace(cloud_images=cloud.runtime, autonomy_queue=cloud.queue)
    )
    client = TestClient(web.app)  # No application lifespan or providers.
    response = client.post(
        "/api/media/generate",
        headers={"X-User-Token": "user-token"},
        json={"kind": "image", "cloud": True, "prompt": "blue square"},
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    assert not cloud.requests
    assert client.get(f"/api/media/generation-tasks/{task_id}").status_code == 401
    headers = {"X-Admin-Token": "owner-token"}
    assert (
        client.get(f"/api/media/generation-tasks/{task_id}", headers=headers).json()["state"]
        == "awaiting_approval"
    )
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    ready = client.get(f"/api/media/generation-tasks/{task_id}", headers=headers).json()
    assert ready["state"] == "ready", ready
    image = client.get(
        "/api/media/generated/" + ready["artifact"]["id"], headers={"X-User-Token": "user-token"}
    )
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    rows = client.get("/api/media/catalog", headers={"X-User-Token": "user-token"}).json()["items"]
    assert rows[0]["available"] and rows[0]["cloud"] is True
    exported = client.post(
        "/api/media/export", headers={"X-User-Token": "user-token"}, json={"ids": [rows[0]["id"]]}
    )
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        import json

        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["missing"] == [] and manifest["items"][0]["id"] == rows[0]["id"]
        assert archive.read("media/" + rows[0]["id"]) == image.content
    assert len(cloud.requests) == 1


def test_coordinator_composes_exact_cloud_and_url_discriminators(cloud, monkeypatch):
    from types import SimpleNamespace

    from agents.core import cloud_image_runtime
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    calls = []

    def previous(task):
        calls.append(task.kind)
        return False

    executor = TaskExecutor(execution_guard=previous)
    executor.register("plugin.egress", lambda task: None)
    monkeypatch.setattr(cloud_image_runtime, "CloudImageRuntime", lambda *a, **k: cloud.runtime)
    orch = SimpleNamespace(autonomy=cloud.worker, secret_broker=SimpleNamespace(redact=lambda x: x))
    AutonomyCoordinator(orch)._wire_cloud_image(executor)
    assert orch.cloud_images is cloud.runtime
    assert (
        executor.execution_guard(SimpleNamespace(kind="plugin.egress", payload={"plugin": "other"}))
        is False
    )
    assert calls == []
    assert (
        executor.execution_guard(
            SimpleNamespace(kind="plugin.egress", payload={"plugin": "job-url-monitor"})
        )
        is False
    )
    assert calls == ["plugin.egress"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["redirect", "multiple", "invalid", "encoded", "overlimit"])
async def test_provider_failures_never_publish_or_follow(cloud, response):
    import httpx

    from agents.core.media_backends.openai_image import MAX_RESPONSE

    bodies = {
        "redirect": lambda: httpx.Response(302, headers={"location": "https://other.test/image"}),
        "multiple": lambda: httpx.Response(200, json={"data": [{}, {}]}),
        "invalid": lambda: httpx.Response(200, json={"data": [{"b64_json": "invalid"}]}),
        "encoded": lambda: httpx.Response(
            200, headers={"content-encoding": "br"}, stream=httpx.ByteStream(b"invalid")
        ),
        "overlimit": lambda: httpx.Response(
            200, stream=httpx.ByteStream(b" " * (MAX_RESPONSE + 1))
        ),
    }
    cloud.state.response = bodies[response]
    task = await finish(cloud)
    assert task.result["status"] != "ok"
    assert len(cloud.requests) == 1
    assert not list((cloud.root / "media" / "generated").glob("*.png"))


@pytest.mark.asyncio
async def test_after_dns_stop_has_no_dial(cloud, monkeypatch):
    from agents.core import estop

    def resolve(*a, **kw):
        monkeypatch.setattr(estop, "is_engaged", lambda: True)
        return ["93.184.216.34"], None

    cloud.runtime.resolver = resolve
    task = await finish(cloud)
    assert not cloud.requests and task.result["status"] != "ok"


@pytest.mark.asyncio
async def test_catalog_opt_out_and_real_runtime_restart(cloud, monkeypatch):
    from agents.core.cloud_image_runtime import CloudImageRuntime

    monkeypatch.setenv("JARVIS_MEDIA_CATALOG", "0")
    task = await finish(cloud)
    assert task.result["status"] == "ok"
    assert not (cloud.root / "media" / "catalog.json").exists()
    restarted = CloudImageRuntime(
        cloud.worker,
        kernel=cloud.kernel,
        redact=lambda x: x,
        root=cloud.root,
        key=lambda: cloud.state.key,
    )
    assert restarted.recover(task) == task.result
    assert restarted.project(task).state == "ready"
    assert len(cloud.requests) == 1


@pytest.mark.asyncio
async def test_cancellation_after_send_preserves_no_replay_marker(cloud):
    import asyncio

    import httpx

    ready = asyncio.Event()

    async def transport(req):
        cloud.requests.append(req)
        ready.set()
        await asyncio.Event().wait()

    cloud.runtime.transport_factory = lambda target: httpx.MockTransport(transport)
    task_id = cloud.runtime.submit("test", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    running = asyncio.create_task(cloud.worker.tick())
    await asyncio.wait_for(ready.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    task = cloud.queue.get(task_id)
    assert cloud.runtime._path(task, "attempt").exists()
    assert len(cloud.requests) == 1
    assert (await cloud.runtime.execute(task))["status"] == "refused"


@pytest.mark.asyncio
async def test_actual_cloud_url_guard_composition_consumes_once(cloud, monkeypatch):
    from types import SimpleNamespace

    import httpx

    from agents.core import cloud_image_runtime
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.jobs_url import URLMonitorExecutor
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from tests.test_job_url_executor import payload

    calls = []
    allowed = cloud.worker.execution_allowed

    def checked(task):
        calls.append(task.id)
        return allowed(task)

    monkeypatch.setattr(cloud.worker, "execution_allowed", checked)
    url = URLMonitorExecutor(
        cloud.worker,
        kernel=cloud.kernel,
        redact=lambda x: x,
        current=lambda p: True,
        resolver=lambda *a, **kw: (["93.184.216.34"], None),
        transport_factory=lambda target: httpx.MockTransport(
            lambda req: httpx.Response(200, stream=httpx.ByteStream(b"unchanged"))
        ),
    )
    executor = TaskExecutor(execution_guard=url.guard)
    executor.register("plugin.egress", url.execute)
    monkeypatch.setattr(cloud_image_runtime, "CloudImageRuntime", lambda *a, **kw: cloud.runtime)
    AutonomyCoordinator(
        SimpleNamespace(autonomy=cloud.worker, secret_broker=SimpleNamespace(redact=lambda x: x))
    )._wire_cloud_image(executor)
    cloud.worker.executor = executor.execute
    task_id = url.submit(payload(), "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    assert cloud.queue.get(task_id).result["status"] == "ok"
    image = await finish(cloud)
    assert image.result["status"] == "ok"
    assert calls == [task_id, image.id]


@pytest.mark.asyncio
async def test_execution_rechecks_heavy_profile_after_approval(cloud, monkeypatch):
    task_id = cloud.runtime.submit("test", {}, "user")
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "gaming")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await cloud.worker.tick()
    assert not cloud.requests


@pytest.mark.asyncio
async def test_a_plugin_switched_off_at_the_live_gate_cannot_submit(cloud, monkeypatch):
    """H285 review F2: the gate holds its own manifests (the toggle and the load set
    switch those), so the runtime asks the gate it was wired with."""
    from types import SimpleNamespace

    from agents.core import cloud_image_runtime
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.plugin_gate import BUILTIN_PLUGINS, PermissionGate

    gate = PermissionGate()
    wired = {}
    monkeypatch.setattr(cloud_image_runtime, "CloudImageRuntime", lambda *a, **kw: wired.update(kw) or cloud.runtime)
    AutonomyCoordinator(SimpleNamespace(autonomy=cloud.worker, permission_gate=gate,
                                        secret_broker=SimpleNamespace(redact=lambda x: x)))._wire_cloud_image(
        TaskExecutor())
    assert wired["gate"] is gate
    cloud.runtime.gate = gate
    gate.disable("cloud-image")
    assert BUILTIN_PLUGINS["cloud-image"].enabled is True
    with pytest.raises(ValueError):
        cloud.runtime.submit("test", {}, "user")
    assert cloud.queue.list() == []
    assert cloud.runtime.status()["configured"] is False


@pytest.mark.asyncio
async def test_disabled_manifest_cannot_submit(cloud, monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    monkeypatch.setattr(BUILTIN_PLUGINS["cloud-image"], "enabled", False)
    with pytest.raises(ValueError):
        cloud.runtime.submit("test", {}, "user")
    assert cloud.queue.list() == []


@pytest.mark.asyncio
async def test_changed_approved_body_cannot_execute(cloud):
    task_id = cloud.runtime.submit("test", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    task = cloud.queue.get(task_id)
    task.payload["image"]["body"]["prompt"] = "replacement"
    # Review round 6, item 6: the guard names a governance decline instead of a bare
    # False (a guard that broke still returns False).
    from agents.core.autonomy.executor import ExecutionGuardDeclined

    with pytest.raises(ExecutionGuardDeclined) as declined:
        cloud.runtime.guard(task)
    assert declined.value.reason == "approved_payload_changed"
    assert (await cloud.runtime.execute(task))["status"] == "refused"
    assert not cloud.requests


def test_catalog_serializes_independent_writers_and_idempotent_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from agents.core.media_catalog import MediaCatalog

    path = tmp_path / "catalog.json"

    def add(index):
        return MediaCatalog(path).add(
            kind="image", prompt=str(index), path="image.png", now=1, record_id=f"md-{index:012x}"
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(add, list(range(16)) * 2))
    assert len({row["id"] for row in rows}) == 16
    assert len(MediaCatalog(path).search(limit=100)) == 16
    with pytest.raises(ValueError, match="collision"):
        MediaCatalog(path).add(
            kind="image", prompt="changed", path="image.png", now=1, record_id="md-000000000000"
        )


def test_known_secret_prompt_refused_before_queue_persistence(cloud):
    with pytest.raises(ValueError, match="prompt screening"):
        cloud.runtime.submit("draw " + cloud.state.key, {}, "user")
    assert cloud.queue.list() == []
    assert not cloud.requests


@pytest.mark.parametrize("behavior", ["raises", "nontext"])
def test_prompt_screening_failure_refuses_before_queue(cloud, behavior):
    def redact(text):
        if behavior == "raises":
            raise RuntimeError("fake sensitive broker error")
        return None

    cloud.runtime.redact = redact
    with pytest.raises(ValueError, match="prompt screening") as error:
        cloud.runtime.submit("blue square", {}, "user")
    assert "sensitive" not in str(error.value)
    assert cloud.queue.list() == []


@pytest.mark.asyncio
async def test_newly_known_secret_after_approval_refuses_without_rewriting(cloud):
    task_id = cloud.runtime.submit("blue square", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    cloud.runtime.redact = lambda text: text.replace("blue", "[redacted]")
    await cloud.worker.tick()
    assert not cloud.requests
    assert cloud.queue.get(task_id).payload["image"]["body"]["prompt"] == "blue square"


@pytest.mark.asyncio
async def test_newly_known_secret_during_dns_refuses_before_dial(cloud):
    def resolve(*args, **kwargs):
        cloud.runtime.redact = lambda text: "[redacted]"
        return ["93.184.216.34"], None

    cloud.runtime.resolver = resolve
    await finish(cloud)
    assert not cloud.requests


def test_cloud_status_is_nonsecret_readonly_and_never_probes(cloud, monkeypatch):
    monkeypatch.setattr(
        cloud.runtime, "_configuration", lambda: pytest.fail("status wrote configuration")
    )
    monkeypatch.setattr(
        type(cloud.worker._mediation_signer), "sign", lambda *args: pytest.fail("status signed data")
    )
    status = cloud.runtime.status()
    assert status["configured"] and status["reachable"] is None
    assert status["provider"] == "openai" and status["model"] == "gpt-image-1.5"
    assert status["approval_required"] is True and status["local"] is False
    assert cloud.state.key not in str(status) and "generation" not in status
    assert not (cloud.root / "media" / "cloud-image").exists()
    assert cloud.queue.list() == [] and not cloud.requests


def test_cloud_status_missing_key_is_unavailable_without_persistence(cloud):
    cloud.state.key = ""
    assert cloud.runtime.status()["configured"] is False
    assert not (cloud.root / "media" / "cloud-image").exists()


def test_media_status_exposes_independent_cloud_capability(cloud, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import image_generation_runtime

    monkeypatch.setattr(web, "USER_TOKEN", "fixture-owner")
    monkeypatch.setattr(web, "orch", SimpleNamespace(cloud_images=cloud.runtime))
    monkeypatch.setattr(
        image_generation_runtime,
        "configuration_status",
        lambda: {"configured": False, "local": True, "approval_required": True},
    )
    response = TestClient(web.app).get("/api/media", headers={"X-User-Token": "fixture-owner"})
    assert response.status_code == 200
    assert response.json()["cloud_image"]["configured"]
    assert response.json()["local_image"]["configured"] is False
    assert response.json()["kinds"]["image"] is True


# ── review round 5, item 8: honest outcomes from the cloud image runtime ──────


def _outcomes(cloud):
    stats = cloud.queue.capability_outcome_stats("action:plugin.egress")
    return stats["successes"], stats["failures"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response, reason", [
    ("http_error", "cloud_image_provider_error"),
    ("redirect", "cloud_image_provider_error"),
    ("encoded", "cloud_image_provider_error"),
    ("overlimit", "cloud_image_response_too_large"),
    ("invalid", "cloud_image_invalid_response"),
])
async def test_a_provider_failure_is_a_failure_under_its_own_reason(cloud, response, reason):
    """Closure MINOR: every failure path returned ``{"status": "unknown"}``, which the
    worker recorded as a SUCCESS. The request was sent and the provider did not deliver
    an image: ``failed`` with a reason, recorded as a failure (0,1)."""
    import httpx

    from agents.core.media_backends.openai_image import MAX_RESPONSE

    bodies = {
        "http_error": lambda: httpx.Response(500, json={"error": {"message": "server error"}}),
        "redirect": lambda: httpx.Response(302, headers={"location": "https://other.test/image"}),
        "encoded": lambda: httpx.Response(
            200, headers={"content-encoding": "br"}, stream=httpx.ByteStream(b"invalid")
        ),
        "overlimit": lambda: httpx.Response(
            200, stream=httpx.ByteStream(b" " * (MAX_RESPONSE + 1))
        ),
        "invalid": lambda: httpx.Response(200, json={"data": [{"b64_json": "invalid"}]}),
    }
    cloud.state.response = bodies[response]
    task = await finish(cloud)
    assert task.result == {"status": "failed", "reason": reason}
    assert len(cloud.requests) == 1
    assert not list((cloud.root / "media" / "generated").glob("*.png"))
    assert _outcomes(cloud) == (0, 1)


@pytest.mark.asyncio
async def test_an_ambiguous_submission_stays_unknown_and_is_recorded_as_a_failure(cloud):
    """A transport error after the dial: the POST may have been processed (and paid), so
    the runtime still says ``unknown`` and never replays it — and the worker records
    ``unknown`` as a failure, never a success (an attempt that could have touched the
    world and did not verifiably succeed)."""
    import httpx

    def lost():
        raise httpx.ReadError("connection reset")

    cloud.state.response = lost
    task = await finish(cloud)
    assert task.result["status"] == "unknown" and len(cloud.requests) == 1
    assert _outcomes(cloud) == (0, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("change, detail", [("deny", "kernel_denied"), ("raise", None)])
async def test_a_kernel_change_after_generation_withholds_only_for_a_denial(cloud, change, detail):
    """Consistent with item 1: the recheck after the provider answered withholds the
    generated image only for a governance cause (a real kernel DENY): recorded as
    nothing. A kernel that RAISES there is the machinery failing: a failure (0,1).
    Neither publishes the image."""
    from dataclasses import replace

    from agents.core.kernel import Verdict

    original, real_kernel = cloud.state.response, cloud.runtime.kernel

    def broken(action, **kwargs):
        if change == "raise":
            raise RuntimeError("policy store unreadable")
        return replace(real_kernel(action, **kwargs), verdict=Verdict.DENY, reason="changed")

    def answered():
        cloud.runtime.kernel = broken                  # after the dial, before the recheck
        return original()

    cloud.state.response = answered
    task = await finish(cloud)
    assert len(cloud.requests) == 1
    assert not list((cloud.root / "media" / "generated").glob("*.png"))
    if detail is not None:
        assert task.result == {"status": "failed", "reason": "withheld_after_generation",
                               "detail": detail}
        assert _outcomes(cloud) == (0, 0)
    else:
        assert task.result == {"status": "failed", "reason": "cloud_image_recheck_failed"}
        assert _outcomes(cloud) == (0, 1)


@pytest.mark.asyncio
async def test_a_stop_before_the_dial_is_a_refusal(cloud, monkeypatch):
    """The emergency stop engaged while the host resolves, before the dial: the
    runtime's own pre-dial check declines — ``refused`` (nothing was sent), recorded as
    nothing (it was ``unknown``, recorded as a success)."""
    from agents.core import estop

    def resolve(*a, **kw):
        monkeypatch.setattr(estop, "is_engaged", lambda: True)
        return ["93.184.216.34"], None

    cloud.runtime.resolver = resolve
    task = await finish(cloud)
    assert task.result == {"status": "refused", "reason": "estop_engaged"}
    assert not cloud.requests
    assert _outcomes(cloud) == (0, 0)


@pytest.mark.asyncio
async def test_a_completed_cloud_image_is_still_a_success(cloud):
    """Guard: the one explicit success (``ok`` from the local completion) records one."""
    task = await finish(cloud)
    assert task.result["status"] == "ok"
    assert _outcomes(cloud) == (1, 0)


# ── review round 6: a broken mediation store, a catalog-only failure, the guard ──


def _break_mediation_store_inside(queue, caller):
    """sqlite raising inside ``validate_mediated_execution`` (its first read), only when
    *caller* — the runtime's own ``live_check`` — asks. Returns the list of hits."""
    import sqlite3
    import sys

    real, hits = queue.validate_mediated_execution, []

    def boom():
        raise sqlite3.OperationalError("disk I/O error")

    def validate(task, fingerprint):
        if sys._getframe(1).f_code.co_name == caller:
            hits.append(caller)
            queue._validated_mediation_snapshot_locked = boom
            try:
                return real(task, fingerprint)
            finally:
                del queue._validated_mediation_snapshot_locked
        return real(task, fingerprint)

    queue.validate_mediated_execution = validate
    return hits


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before_the_dial", "after_generation"])
async def test_a_mediation_store_that_breaks_is_a_failure_not_a_governance_hold(cloud, when):
    """Closure P2 / hunt MINOR 2 (round 6, item 2): ``validate_mediated_execution``
    swallowed a database or signer error into False, which ``live_check`` reported as
    the governance decline ``mediation_execution_required``: refused before the dial,
    withheld after generation — (0,0) either way. The store failing is the machinery:
    ``mediation_state_unavailable``, a failure (0,1). The image is never published."""
    armed = {}
    if when == "before_the_dial":
        def resolve(*a, **kw):
            armed["hits"] = _break_mediation_store_inside(cloud.queue, "live_check")
            return ["93.184.216.34"], None

        cloud.runtime.resolver = resolve
    else:
        original = cloud.state.response

        def answered():
            armed["hits"] = _break_mediation_store_inside(cloud.queue, "live_check")
            return original()

        cloud.state.response = answered
    task = await finish(cloud)
    assert armed["hits"]
    assert task.result == {"status": "failed", "reason": "mediation_state_unavailable"}
    assert len(cloud.requests) == (0 if when == "before_the_dial" else 1)
    assert not list((cloud.root / "media" / "generated").glob("*.png"))
    assert _outcomes(cloud) == (0, 1)


@pytest.mark.asyncio
async def test_a_published_image_whose_catalog_row_failed_is_a_success(cloud, monkeypatch):
    """Hunt MINOR 3 (round 6, item 3): the image was generated, rechecked, saved under
    media/generated and its durable completion record written; only the catalog row
    failed. That delivered the image: ``ok`` with a warning naming the catalog step
    (it was ``unknown``, a failure), consistent with the local image path — and a later
    ``recover`` still adds the row, with no new request."""
    from agents.core.media_catalog import MediaCatalog

    original = MediaCatalog.add
    monkeypatch.setattr(MediaCatalog, "add",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("catalog store is unreadable")))
    task = await finish(cloud)
    pngs = list((cloud.root / "media" / "generated").glob("*.png"))
    assert task.result["status"] == "ok", task.result
    assert task.result["warning"] == "catalog_record_failed"
    assert "catalog_id" not in task.result["result"]
    assert len(pngs) == 1 and len(cloud.requests) == 1
    assert _outcomes(cloud) == (1, 0)
    monkeypatch.setattr(MediaCatalog, "add", original)
    later = cloud.runtime.recover(task)
    assert later["status"] == "ok" and "warning" not in later
    assert later["result"]["catalog_id"] and len(cloud.requests) == 1


@pytest.mark.asyncio
async def test_an_image_not_durably_kept_locally_stays_unknown(cloud, monkeypatch):
    """The contrast: the provider answered and the recheck passed, but the completion
    record could not be written — the image may exist remotely and is not durably kept
    here: still ``unknown`` (a failure), never replayed."""
    from agents.core import cloud_image_runtime

    real_write = cloud_image_runtime._write

    def write(path, data, *, replace=False):
        if path.name.endswith(".complete"):
            raise OSError("disk full")
        return real_write(path, data, replace=replace)

    monkeypatch.setattr(cloud_image_runtime, "_write", write)
    task = await finish(cloud)
    assert task.result["status"] == "unknown", task.result
    assert len(cloud.requests) == 1
    assert _outcomes(cloud) == (0, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("gate, reason", [
    ("key_rotated", "configuration_changed"),
    ("heavy_paused", "cloud_image_unavailable"),
    ("plugin_disabled", "cloud_image_unavailable"),
])
async def test_a_governance_decline_at_the_execution_guard_records_nothing(
        cloud, monkeypatch, gate, reason):
    """Hunt NIT 4 / closure P3 (round 6, item 6): the execution guard runs the same gates
    as ``execute``'s preflight, but returned a bare False — ``mediation_execution_context_
    required`` — which the worker recorded as a FAILURE, so the pre-dial ``refused``
    mapping was reachable only by a race. The guard now reports its reason: a governance
    decline in the kind's refusal vocabulary, before any attempt, records nothing."""
    task_id = cloud.runtime.submit("blue square", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    if gate == "key_rotated":
        cloud.state.key = "rotated-credential"
    elif gate == "heavy_paused":
        monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "gaming")
    else:
        from dataclasses import replace

        from agents.core import plugin_gate
        plugins = dict(plugin_gate.BUILTIN_PLUGINS)
        plugins["cloud-image"] = replace(plugins["cloud-image"], enabled=False)
        monkeypatch.setattr(plugin_gate, "BUILTIN_PLUGINS", plugins)
    await cloud.worker.tick()
    task = cloud.queue.get(task_id)
    assert not cloud.requests
    assert task.status == "failed"
    assert task.result.get("guard_reason") == reason, task.result
    assert _outcomes(cloud) == (0, 0)


@pytest.mark.asyncio
async def test_an_execution_guard_that_broke_is_still_a_failure(cloud):
    """The contrast: the guard's own machinery failing (the signer gives no signature) is
    not a governance decline — no reason is reported, and it records a failure (0,1)."""
    task_id = cloud.runtime.submit("blue square", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    signer = cloud.worker._mediation_signer

    class Unsigning:
        def sign(self, data):
            return None

        def __getattr__(self, name):
            return getattr(signer, name)

    cloud.worker._mediation_signer = Unsigning()
    await cloud.worker.tick()
    task = cloud.queue.get(task_id)
    assert not cloud.requests
    assert task.status == "failed" and "guard_reason" not in task.result, task.result
    assert _outcomes(cloud) == (0, 1)


@pytest.mark.asyncio
async def test_a_mediation_store_that_breaks_at_dispatch_fails_the_task_before_the_handler(cloud):
    """Round 6, item 2, the worker's own pre-dispatch check: a store that cannot be read
    fails the task before any handler runs (as a refused validation always did), names
    the store, and records nothing for the capability — the handler never ran."""
    hits = _break_mediation_store_inside(cloud.queue, "tick")
    task = await finish(cloud)
    assert hits and not cloud.requests
    assert task.status == "failed"
    assert task.result == {"error": "mediation state unavailable"}
    assert _outcomes(cloud) == (0, 0)


@pytest.mark.asyncio
async def test_a_mediation_store_that_breaks_during_the_intake_observation_changes_nothing(cloud):
    """The QA4 intake observation asks the same check only to decide whether evidence is
    missing; a store it cannot read there proves no receipt (not exempt) and never
    changes the task's execution — it still completes, one request, one success."""
    hits = _break_mediation_store_inside(cloud.queue, "_has_valid_b7_receipt")
    task = await finish(cloud)
    assert hits
    assert task.result["status"] == "ok" and len(cloud.requests) == 1
    assert _outcomes(cloud) == (1, 0)


@pytest.mark.asyncio
async def test_a_kernel_or_screen_that_is_not_wired_is_a_failure_at_the_guard(cloud):
    """Round 6, item 6: the guard now names a governance decline, so what it names must
    be one. Mediation not enforced or the kernel switched off is configuration
    (``enforced_mediation_unavailable``, a refusal); a kernel callable that is missing
    is a component that failed to start — machinery: no reason, a failure (0,1)."""
    task_id = cloud.runtime.submit("blue square", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    cloud.runtime.kernel = None
    await cloud.worker.tick()
    task = cloud.queue.get(task_id)
    assert not cloud.requests
    assert task.status == "failed" and "guard_reason" not in task.result, task.result
    assert _outcomes(cloud) == (0, 1)


@pytest.mark.asyncio
async def test_the_kernel_switched_off_is_a_refusal_at_the_guard(cloud, monkeypatch):
    """The contrast: the action kernel switched off after the approval is configuration —
    ``enforced_mediation_unavailable``, a refusal before any attempt (0,0)."""
    task_id = cloud.runtime.submit("blue square", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
    await cloud.worker.tick()
    task = cloud.queue.get(task_id)
    assert not cloud.requests
    assert task.status == "failed"
    assert task.result.get("guard_reason") == "enforced_mediation_unavailable", task.result
    assert _outcomes(cloud) == (0, 0)
