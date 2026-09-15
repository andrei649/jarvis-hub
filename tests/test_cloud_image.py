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
    assert task.result["status"] == "unknown" and len(cloud.requests) == 1
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
    assert task.result["status"] == "unknown"
    assert not list((cloud.root / "media" / "generated").glob("*.png"))


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
    assert cloud.runtime.guard(task) is False
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
