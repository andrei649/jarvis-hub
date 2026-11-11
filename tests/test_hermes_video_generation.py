"""G19 / H516 — video generation through the adopted Hermes providers, from the owner's side.

Every leg runs against a fake provider at the egress transport (``httpx.MockTransport``
behind the task's ``PluginHTTPClient``): no network. What is proven:

* the providers are off until the owner sets a key and chooses one with consent;
* the tool only proposes: one approval card whose title and payload carry the cost
  estimate (``amount``), refused under the e-stop and in plan mode;
* an approved video runs the vendored provider code, every request goes only to that
  provider's hosts and carries only its own key, polling is bounded and cancellable, the
  file is size-capped, checked and saved as a media artifact the owner can open;
* the vendored bytes match the manifest, the CI allowlist covers them, and the
  Integrations panel lists the providers.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

REPORTED_TICKS = 3_000_000_000
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 200


def _respond_fal(state):
    def handler(request):
        host = request.headers.get("host", "")
        path = request.url.path
        if host == "queue.fal.run" and request.method == "POST":
            return httpx.Response(200, json={
                "request_id": "req-1",
                "status_url": "https://queue.fal.run/fal-ai/pixverse/requests/req-1/status",
                "response_url": "https://queue.fal.run/fal-ai/pixverse/requests/req-1"})
        if host == "queue.fal.run" and path.endswith("/status"):
            state.polls += 1
            if state.hang:
                return httpx.Response(200, json={"status": "IN_PROGRESS"})
            return httpx.Response(200, json={"status": "COMPLETED" if state.polls >= 2 else "IN_QUEUE"})
        if host == "queue.fal.run":
            return httpx.Response(200, json={"video": {"url": state.video_url, "content_type": "video/mp4"}})
        if host.endswith("fal.media"):
            return httpx.Response(200, content=state.video, headers={"content-type": "video/mp4"})
        return httpx.Response(404)
    return handler


def _respond_xai(state):
    def handler(request):
        host = request.headers.get("host", "")
        if host == "api.x.ai" and request.method == "POST":
            return httpx.Response(200, json={"request_id": "xr-1"})
        if host == "api.x.ai":
            return httpx.Response(200, json={
                "status": "done", "model": "grok-imagine-video",
                "video": {"url": "https://vidgen.x.ai/xai-vidgen-bucket/v.mp4", "duration": 6},
                "usage": {"cost_in_usd_ticks": REPORTED_TICKS}})
        if host == "vidgen.x.ai":
            return httpx.Response(200, content=state.video, headers={"content-type": "video/mp4"})
        return httpx.Response(404)
    return handler


@pytest.fixture
def video(tmp_path, monkeypatch):
    from agents.core import integration_keys
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.creative.video_generation import CloudVideoRuntime
    from agents.core.kernel.binding import make_action_kernel
    from agents.vendor.hermes_compat import video_shared
    from tests.test_task_mediation_evidence import _head_anchor, _signer

    for name in ("FAL_KEY", "XAI_API_KEY", "DEEPINFRA_API_KEY", "JARVIS_VIDEO_PROVIDER",
                 "NERVA_VIDEO_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "balanced")
    monkeypatch.setenv("FAL_KEY", "fal-fixture-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-fixture-key")
    monkeypatch.setenv("JARVIS_VIDEO_PROVIDER", "fal")
    monkeypatch.setattr(video_shared, "FAL_POLL_SECONDS", 0.01)
    path = tmp_path / "queue.db"
    queue = TaskQueue(str(path), mediation_mode="enforce", mediation_signer=_signer(),
                      mediation_head_anchor=_head_anchor(path), mediation_scope="global").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    orch = SimpleNamespace(autonomy=worker, kill_switch=None, capabilities=None, intent_log=None,
                           budget_ledger=None, loop_detector=None)
    kernel = make_action_kernel(orch)
    worker.bind_mediation(kernel, _signer())
    requests = []
    state = SimpleNamespace(polls=0, hang=False, video=MP4,
                            video_url="https://v3b.fal.media/files/b/out.mp4", provider="fal")

    def transport(request):
        requests.append(request)
        return {"fal": _respond_fal, "xai": _respond_xai, "deepinfra": _respond_deepinfra,
                "deepinfra-cdn": _respond_deepinfra_cdn}[state.provider](state)(request)

    runtime = CloudVideoRuntime(
        worker, kernel=kernel, redact=lambda s: s.replace("fal-fixture-key", "[redacted]"),
        root=tmp_path, resolver=lambda *a, **kw: (["93.184.216.34"], None),
        transport_factory=lambda target: httpx.MockTransport(transport))
    executor = TaskExecutor(execution_guard=runtime.guard)
    executor.register("plugin.egress", runtime.execute)
    worker.executor = executor.execute
    yield SimpleNamespace(runtime=runtime, worker=worker, queue=queue, requests=requests,
                          state=state, root=tmp_path, kernel=kernel)
    queue.close()
    integration_keys.reset_for_tests()


async def _approve(video, task_id):
    await video.worker.apply_decision(task_id, "accept", decided_by="test owner")
    await video.worker.tick()
    return video.queue.get(task_id)


# ── off until key + consent ──────────────────────────────────────────────────────

def test_no_provider_without_consented_choice_or_key(video, monkeypatch):
    monkeypatch.delenv("JARVIS_VIDEO_PROVIDER")
    with pytest.raises(Exception) as caught:
        video.runtime.submit({"prompt": "a cat"}, "user")
    assert "provider" in str(getattr(caught.value, "reason", caught.value))
    monkeypatch.setenv("JARVIS_VIDEO_PROVIDER", "fal")
    monkeypatch.delenv("FAL_KEY")
    with pytest.raises(Exception) as caught:
        video.runtime.submit({"prompt": "a cat"}, "user")
    assert getattr(caught.value, "reason", "") == "credential_not_configured"
    # choosing a provider the owner did not choose is refused even with its key set
    monkeypatch.setenv("FAL_KEY", "fal-fixture-key")
    with pytest.raises(Exception) as caught:
        video.runtime.submit({"prompt": "a cat", "provider": "xai"}, "user")
    assert getattr(caught.value, "reason", "") == "video_provider_not_chosen"
    assert not video.requests


# ── the card, the run, the artifact ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approved_fal_video_runs_vendored_code_to_its_hosts_and_is_served(video):
    from agents.core.artifact_store import resolve_blob

    task_id = video.runtime.submit({"prompt": "a red fox runs", "duration": 5}, "user")
    task = video.queue.get(task_id)
    assert task.status == "blocked" and task.autonomy_level == "ask"
    assert task.payload["plugin"] == "cloud-video-fal"
    assert task.payload["url"] == "https://queue.fal.run/fal-ai/pixverse/v6/text-to-video"
    cost = task.payload["video"]["cost"]
    # Pixverse v6 at 720p, audio left to the endpoint (counted as on): $0.060/s x 5 s
    assert cost["seconds"] == 5 and cost["usd"] == pytest.approx(0.30) and task.payload["amount"] == cost["usd"]
    assert "up to $0.30" in task.title
    assert not video.requests
    task = await _approve(video, task_id)
    assert task.result["status"] == "ok", task.result
    hosts = [(r.method, r.headers["host"]) for r in video.requests]
    assert hosts[0] == ("POST", "queue.fal.run")
    assert {h for _m, h in hosts} <= {"queue.fal.run", "v3b.fal.media"}
    # the key goes only to the queue host, never to the media CDN
    for request in video.requests:
        if request.headers["host"] == "queue.fal.run":
            assert request.headers["authorization"] == "Key fal-fixture-key"
        else:
            assert "authorization" not in request.headers
    body = json.loads(video.requests[0].content)
    assert body["prompt"] == "a red fox runs" and body["duration"] == "5"
    artifact = task.result["result"]["result"]
    assert artifact["mime"] == "video/mp4" and artifact["bytes"] == len(MP4)
    meta, data = resolve_blob(artifact["catalog_id"], video.root)
    assert data == MP4 and meta["mime"] == "video/mp4"
    # no replay: a second run of the same task recovers, it never dials again
    count = len(video.requests)
    assert video.runtime.recover(video.queue.get(task_id))["status"] == "ok"
    assert len(video.requests) == count


@pytest.mark.asyncio
async def test_xai_key_goes_only_to_xai_and_reported_cost_is_recorded(video, monkeypatch):
    monkeypatch.setenv("JARVIS_VIDEO_PROVIDER", "xai")
    video.state.provider = "xai"
    task_id = video.runtime.submit({"prompt": "waves", "duration": 6, "resolution": "1080p"}, "user")
    task = video.queue.get(task_id)
    assert task.payload["video"]["body"]["resolution"] == "720p"  # upstream's fallback, shown on the card
    task = await _approve(video, task_id)
    assert task.result["status"] == "ok", task.result
    for request in video.requests:
        if request.headers["host"] == "api.x.ai":
            assert request.headers["authorization"] == "Bearer xai-fixture-key"
            assert request.headers["user-agent"] == "Nerva"
        else:
            assert request.headers["host"] == "vidgen.x.ai" and "authorization" not in request.headers
    assert all("fal-fixture-key" not in str(r.headers) for r in video.requests)
    assert task.result["cost"]["reported_usd"] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_a_provider_url_on_another_host_is_never_fetched(video):
    video.state.video_url = "https://evil.example/steal.mp4"
    task_id = video.runtime.submit({"prompt": "a red fox"}, "user")
    task = await _approve(video, task_id)
    assert task.result["status"] == "refused", task.result
    assert all(r.headers["host"] != "evil.example" for r in video.requests)


@pytest.mark.asyncio
async def test_download_over_the_cap_is_refused_and_nothing_is_kept(video):
    video.runtime.max_bytes = 100
    task_id = video.runtime.submit({"prompt": "a red fox"}, "user")
    task = await _approve(video, task_id)
    assert task.result["status"] == "failed" and task.result["reason"] == "video_too_large", task.result
    assert not list((video.root / "media").rglob("*.mp4"))


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_video_is_refused(video):
    video.state.video = b"<html>not a video</html>"
    task_id = video.runtime.submit({"prompt": "a red fox"}, "user")
    task = await _approve(video, task_id)
    assert task.result["status"] == "failed" and task.result["reason"] == "video_unrecognized"


def _respond_deepinfra(state):
    def handler(request):
        host, path = request.headers.get("host", ""), request.url.path
        assert host == "api.deepinfra.com"
        if request.method == "POST":
            state.bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "vid_1", "status": "queued"})
        if path.endswith("/content"):
            return httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"})
        return httpx.Response(200, json={"id": "vid_1", "status": "succeeded", "data": []})
    return handler


@pytest.mark.asyncio
async def test_deepinfra_runs_the_openai_videos_flow_through_the_stand_in(video, monkeypatch):
    from agents.vendor.hermes_compat import video_clock

    monkeypatch.setenv("JARVIS_VIDEO_PROVIDER", "deepinfra")
    monkeypatch.setenv("DEEPINFRA_API_KEY", "di-fixture-key")
    monkeypatch.setattr(video_clock, "MAX_SLEEP_SECONDS", 0.01)
    video.state.provider = "deepinfra"
    video.state.bodies = []
    with pytest.raises(ValueError):  # no live catalog: DeepInfra needs a named model
        video.runtime.submit({"prompt": "rain"}, "user")
    task_id = video.runtime.submit({"prompt": "rain", "model": "Wan-AI/Wan2.6-T2V", "duration": 4}, "user")
    task = video.queue.get(task_id)
    assert task.payload["url"] == "https://api.deepinfra.com/v1/openai/videos"
    task = await _approve(video, task_id)
    assert task.result["status"] == "ok", task.result
    assert video.state.bodies == [{"model": "Wan-AI/Wan2.6-T2V", "prompt": "rain", "seconds": "4",
                                   "size": "720p", "aspect_ratio": "16:9"}]
    assert {r.headers["authorization"] for r in video.requests} == {"Bearer di-fixture-key"}


@pytest.mark.asyncio
async def test_image_to_video_sends_an_owned_artifact_as_a_data_uri_bound_to_the_card(video):
    import base64
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(buffer, format="PNG")
    png = buffer.getvalue()
    generated = video.root / "media" / "generated"
    generated.mkdir(parents=True)
    (generated / ("a" * 32 + ".png")).write_bytes(png)
    task_id = video.runtime.submit({"prompt": "animate", "image": "a" * 32}, "user")
    task = video.queue.get(task_id)
    assert task.payload["url"] == "https://queue.fal.run/fal-ai/pixverse/v6/image-to-video"
    assert task.payload["video"]["body"]["image_sha256"][0]
    task = await _approve(video, task_id)
    assert task.result["status"] == "ok", task.result
    sent = json.loads(video.requests[0].content)
    assert sent["image_url"] == "data:image/png;base64," + base64.b64encode(png).decode()
    # an image the model names by a path or a foreign URL is refused before any card
    for bad in ("/etc/passwd", "https://evil.example/x.png", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            video.runtime.submit({"prompt": "animate", "image": bad}, "user")


@pytest.mark.asyncio
async def test_xai_extend_uses_the_video_nerva_generated_with_xai(video, monkeypatch):
    monkeypatch.setenv("JARVIS_VIDEO_PROVIDER", "xai")
    video.state.provider = "xai"
    first = await _approve(video, video.runtime.submit({"prompt": "waves"}, "user"))
    assert first.result["status"] == "ok", first.result
    video.requests.clear()
    task_id = video.runtime.submit({"prompt": "longer", "operation": "extend", "source_task_id": first.id,
                                    "duration": 4}, "user")
    task = video.queue.get(task_id)
    assert task.payload["url"] == "https://api.x.ai/v1/videos/extensions"
    assert task.payload["video"]["body"]["source_url"].startswith("https://vidgen.x.ai/")
    task = await _approve(video, task_id)
    assert task.result["status"] == "ok", task.result
    sent = json.loads(video.requests[0].content)
    assert sent["video"] == {"url": "https://vidgen.x.ai/xai-vidgen-bucket/v.mp4"} and sent["duration"] == 4
    with pytest.raises(ValueError):  # a task that is not an approved xAI video is no source
        video.runtime.submit({"prompt": "x", "operation": "edit", "source_task_id": 999}, "user")


# ── e-stop, plan mode, cancellation ──────────────────────────────────────────────

def test_estop_refuses_the_proposal(video, monkeypatch):
    from agents.core import estop

    monkeypatch.setattr(estop, "is_engaged", lambda: True)
    with pytest.raises(Exception) as caught:
        video.runtime.submit({"prompt": "a red fox"}, "user")
    assert caught.value.reason == "estop_engaged"


@pytest.mark.asyncio
async def test_estop_engaged_mid_poll_stops_the_job(video, monkeypatch):
    from agents.core import estop

    video.state.hang = True
    task_id = video.runtime.submit({"prompt": "a red fox"}, "user")
    await video.worker.apply_decision(task_id, "accept", decided_by="test owner")
    engaged = {"on": False}
    monkeypatch.setattr(estop, "is_engaged", lambda: engaged["on"])

    async def flip():
        while video.state.polls < 2:
            await asyncio.sleep(0.01)
        engaged["on"] = True

    flipper = asyncio.create_task(flip())
    await video.worker.tick()
    await flipper
    task = video.queue.get(task_id)
    assert task.result["status"] == "refused" and task.result["reason"] == "estop_engaged", task.result
    assert task.result["submission_replayed"] is False


@pytest.mark.asyncio
async def test_polling_is_bounded_by_the_deadline(video):
    video.state.hang = True
    video.runtime.deadline = 0.5
    task_id = video.runtime.submit({"prompt": "a red fox"}, "user")
    started = time.monotonic()
    task = await _approve(video, task_id)
    assert time.monotonic() - started < 10
    # the submit was sent, so the outcome is never replayed
    assert task.result["status"] in {"failed", "unknown"}, task.result
    assert task.result.get("submission_replayed", False) is False


@pytest.mark.asyncio
async def test_cancelling_the_task_stops_the_worker_thread(video):
    from agents.core.creative import video_generation

    video.state.hang = True
    task_id = video.runtime.submit({"prompt": "a red fox"}, "user")
    await video.worker.apply_decision(task_id, "accept", decided_by="test owner")
    run = asyncio.create_task(video.worker.tick())
    while video.state.polls < 2:
        await asyncio.sleep(0.01)
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    # the abandoned worker's sleep wakes and its next request is refused: polling stops
    await asyncio.sleep(0.5)
    settled = video.state.polls
    await asyncio.sleep(0.5)
    assert video.state.polls == settled
    # the executor is free again: a trivial job runs at once
    done = video_generation._EXECUTOR.submit(lambda: "free")
    assert done.result(timeout=5) == "free"


@pytest.mark.asyncio
async def test_tool_proposes_one_card_and_plan_mode_refuses_it(video, monkeypatch, tmp_path):
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.kernel import plan_mode

    orch = SimpleNamespace(agents={}, autonomy=video.worker, autonomy_queue=video.queue,
                           cloud_videos=video.runtime, intent_log=None, secret_broker=None)
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=video.worker.kernel_gate)
    server = orch.tool_rpc
    answer = await server.handle({"tool": "video_generate", "args": {"prompt": "a red fox", "duration": 4}},
                                 actor="athena")
    assert answer["reason"] == "approval_required", answer
    task = video.queue.get(answer["task_id"])
    assert task.agent == "athena" and task.payload["amount"] > 0 and not video.requests
    bad = await server.handle({"tool": "video_generate", "args": {"prompt": "x", "provider": "openrouter"}})
    assert bad["ok"] is False and "task_id" not in bad
    store = plan_mode.PlanModeStore(tmp_path / "plan.json")
    store.enter("s1", owner=True, by="owner")
    monkeypatch.setattr(plan_mode, "_DEFAULT", store)
    monkeypatch.setattr(plan_mode, "current_session", lambda: "s1")
    before = len(video.queue.list_tasks()) if hasattr(video.queue, "list_tasks") else None
    refused = await server.handle({"tool": "video_generate", "args": {"prompt": "a red fox"}})
    assert refused["ok"] is False and refused["reason"] == "plan_mode", refused
    assert "task_id" not in refused
    if before is not None:
        assert len(video.queue.list_tasks()) == before


def test_plan_mode_kernel_denies_the_video_post():
    from agents.core.kernel.plan_mode import kind_is_read

    assert kind_is_read("plugin.egress", {"method": "POST"}) is False


# ── adoption: bytes, allowlist, ctx, keys, catalog ───────────────────────────────

def test_vendored_video_files_match_the_manifest_and_the_allowlist():
    import hashlib
    from pathlib import Path

    import scripts.hermes_vendor as hv

    manifest = json.loads(hv.MANIFEST_PATH.read_text())
    rows = [f for f in manifest["files"] if f["path"].startswith(hv.VIDEO_PATHS)]
    assert {r["path"] for r in rows} >= {
        "agent/video_gen_provider.py", "agent/video_gen_registry.py",
        "plugins/video_gen/fal/__init__.py", "plugins/video_gen/xai/__init__.py",
        "plugins/video_gen/deepinfra/__init__.py"}
    assert not any("openrouter" in r["path"] for r in rows)
    for row in rows:
        data = (hv.VENDOR_ROOT / row["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["vendored_sha256"]
        assert hv.content_problems(data, row["path"]) == []
    # the video compat modules are path-scoped: no other vendored file may import them
    text = "from agents.vendor.hermes_compat import video_media as provider_media\n"
    assert hv.unmapped_imports(text, "plugins/web/exa/provider.py")
    assert not hv.unmapped_imports(text, "agent/video_gen_provider.py")
    assert Path(hv.VENDOR_ROOT / "plugins/video_gen/__init__.py").exists()


def test_only_reviewed_providers_register_and_each_reads_only_its_key(monkeypatch):
    from agents.core.creative import video_providers as vp
    from agents.vendor.hermes_compat.video_shared import get_secret_str
    from agents.vendor.hermes_compat.web_search_provider import provider_scope

    reg = vp.registry()
    assert sorted(p.name for p in reg.list_providers()) == ["deepinfra", "fal", "xai"]
    with pytest.raises(ValueError):
        vp._VideoCtx(reg).register_video_gen_provider(SimpleNamespace(name="openrouter"))
    monkeypatch.setenv("FAL_KEY", "f")
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.setenv("DEEPINFRA_BASE_URL", "https://evil.example")
    with provider_scope("fal"):
        assert get_secret_str("FAL_KEY") == "f" and get_secret_str("XAI_API_KEY") == ""
    with provider_scope("xai"):
        assert get_secret_str("XAI_API_KEY") == "x" and get_secret_str("FAL_KEY") == ""
    with provider_scope("deepinfra"):
        assert get_secret_str("DEEPINFRA_BASE_URL") == ""
    assert get_secret_str("FAL_KEY") == ""


def test_xai_plugin_never_reads_a_local_file(tmp_path):
    from agents.core.creative import video_providers as vp

    secret = tmp_path / "id_rsa.png"
    secret.write_bytes(b"\x89PNG secret")
    xai = vp.plugin_module("xai")
    assert xai._image_ref_to_xai_input(str(secret)) is None


def test_requests_are_refused_without_an_approved_task_binding():
    from agents.vendor.hermes_compat import httpx as compat
    from agents.vendor.hermes_compat import video_media

    with pytest.raises(compat.EgressRefused):
        compat.get("https://queue.fal.run/x")
    with pytest.raises(video_media.SinkRefused):
        video_media.save_bytes("videos", MP4)


@pytest.mark.parametrize("args, usd", [
    # verified list prices (2026-11-10): rate x the seconds the provider will bill
    ({"provider": "fal", "model": "seedance-2.0", "resolution": "1080p", "duration": 15}, 10.23),
    ({"provider": "fal", "model": "seedance-2.0", "resolution": "1080p"}, 10.23),     # unset: family max
    ({"provider": "fal", "model": "kling-v3-4k", "duration": 15}, 6.30),
    ({"provider": "fal", "model": "veo3.1", "resolution": "1080p", "duration": 8, "audio": True}, 3.20),
    ({"provider": "fal", "model": "veo3.1", "resolution": "1080p", "duration": 8, "audio": False}, 1.60),
    ({"provider": "fal", "model": "minimax-h3", "resolution": "1080p", "duration": 15}, 1.95),   # 2K
    ({"provider": "fal", "model": "wan-3.0", "resolution": "1080p"}, 6.00),                    # 30 s
    ({"provider": "fal", "model": "flux-3", "resolution": "1080p", "duration": 20}, 5.80),
    ({"provider": "fal", "model": "happy-horse", "resolution": "1080p", "duration": 15}, 2.70),
    ({"provider": "xai", "model": "grok-imagine-video", "duration": 10}, 0.70),
    ({"provider": "deepinfra", "model": "Wan-AI/Wan3.0-Video", "duration": 10}, 2.00),
])
def test_the_card_estimate_is_the_verified_list_price(args, usd, monkeypatch):
    from agents.core.creative import video_providers as vp

    body = vp.normalize_request({"prompt": "x", **args})
    cost = vp.estimate(body)
    assert cost["usd"] == pytest.approx(usd) and cost["basis"].startswith("list price checked")


@pytest.mark.parametrize("args", [
    {"provider": "fal", "model": "ltx-2.3", "duration": 10},                  # priced per megapixel
    {"provider": "fal", "model": "seedance-2.5", "duration": 10},             # no verified price
    {"provider": "fal", "model": "seedance-2.0", "resolution": "480p"},       # resolution not listed
    {"provider": "fal", "model": "flux-3", "image": "a" * 32},                # image-to-video not verified
    {"provider": "xai", "model": "grok-imagine-video-9-ultra"},
    {"provider": "deepinfra", "model": "Wan-AI/Wan2.1-T2V-14B", "duration": 5},
])
def test_a_model_or_setting_without_a_verified_price_is_refused(args):
    from agents.core.creative import video_providers as vp

    with pytest.raises(vp.VideoRequestError, match="price_unverified"):
        vp.normalize_request({"prompt": "x", **args})


@pytest.mark.asyncio
async def test_a_second_post_on_the_api_host_is_refused(video, monkeypatch):
    """Review repro: upstream's SeedVR upscale pass is a second billed submit."""
    from agents.core.creative import video_providers as vp

    prov = vp.provider("fal")
    orig = type(prov).generate
    monkeypatch.setattr(type(prov), "generate", lambda self, p, **kw: orig(self, p, upscale=True, **kw))
    task = await _approve(video, video.runtime.submit({"prompt": "a red fox runs", "duration": 5}, "user"))
    posts = [r for r in video.requests if r.method == "POST"]
    assert len(posts) == 1 and posts[0].url.path.endswith("/text-to-video")
    # the extra submit is refused before it is sent; Nerva never asks for it (no upscale option)
    assert task.result["status"] == "refused" and task.result["reason"] == "dispatch_changed", task.result


def test_registry_export_binds_only_the_video_registry():
    import logging

    import scripts.hermes_vendor as hv
    from agents.vendor.hermes_compat import providers as other
    from agents.vendor.hermes_compat.video_shared import ProviderRegistry

    before = other.register_provider
    with pytest.raises(ValueError):
        ProviderRegistry(label="x", provider_cls=object, logger=logging.getLogger("x")).export(other.__name__)
    assert other.register_provider is before
    assert hv.unmapped_imports("_registry.export(__name__)\n", "agent/video_gen_registry.py") == []
    assert hv.unmapped_imports("_registry.export('agents.x')\n", "agent/video_gen_registry.py")
    assert hv.unmapped_imports("_registry.export(__name__)\n", "plugins/video_gen/fal/__init__.py")


@pytest.mark.asyncio
async def test_xai_edit_is_priced_on_the_source_length_and_a_higher_reported_cost_is_charged(video, monkeypatch):
    monkeypatch.setenv("JARVIS_VIDEO_PROVIDER", "xai")
    video.state.provider = "xai"
    first = await _approve(video, video.runtime.submit({"prompt": "waves"}, "user"))
    assert first.result["status"] == "ok", first.result
    task_id = video.runtime.submit({"prompt": "add snow", "operation": "edit", "source_task_id": first.id}, "user")
    body = video.queue.get(task_id).payload["video"]["body"]
    cost = video.queue.get(task_id).payload["video"]["cost"]
    # the source reported 6 s: output 6 s at $0.07 + input 6 s at $0.01
    assert body["source_seconds"] == 6 and body["billed_seconds"] == 6
    assert cost["usd"] == pytest.approx(0.48)
    extend = video.runtime.submit({"prompt": "more", "operation": "extend", "source_task_id": first.id,
                                   "duration": 4}, "user")
    assert video.queue.get(extend).payload["video"]["cost"]["usd"] == pytest.approx(0.07 * 4 + 0.01 * 6)
    # the provider reports $1.00 for the edit: warned, and the spend carries the real amount
    from tests import test_hermes_video_generation as me

    monkeypatch.setattr(me, "REPORTED_TICKS", 10_000_000_000)
    before = video.worker.policy._spent_today
    task = await _approve(video, task_id)
    assert task.result["status"] == "ok" and task.result["warning"] == "reported_cost_above_estimate"
    assert task.result["cost"]["reported_usd"] == pytest.approx(1.0)
    assert video.worker.policy._spent_today - before == pytest.approx(1.0)


def test_video_manifests_ship_disabled_and_open_only_for_the_chosen_provider(video, monkeypatch):
    from agents.core.creative.video_generation import _VideoClient
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    assert all(BUILTIN_PLUGINS[f"cloud-video-{n}"].enabled is False for n in ("fal", "xai", "deepinfra"))
    fal = _VideoClient(lambda *a: None, plugin="cloud-video-fal")
    assert fal._manifest_mode("https://queue.fal.run/x") == "public"          # fal is chosen
    xai = _VideoClient(lambda *a: None, plugin="cloud-video-xai")
    with pytest.raises(PermissionError):
        xai._manifest_mode("https://api.x.ai/v1/videos/generations")         # not chosen


def _respond_deepinfra_cdn(state):
    def handler(request):
        host, path = request.headers.get("host", ""), request.url.path
        if host != "api.deepinfra.com":
            state.offhost += 1
            return httpx.Response(200, content=MP4)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "vid_9", "status": "queued"})
        if path.endswith("/content"):
            return httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"})
        return httpx.Response(200, json={"id": "vid_9", "status": "succeeded",
                                         "data": [{"url": state.delivery}]})
    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["https://cdn.deepinfra-media.example/v.mp4", "data-uri"])
async def test_a_paid_deepinfra_video_is_not_lost_to_its_delivery_url(video, monkeypatch, delivery):
    import base64

    from agents.vendor.hermes_compat import video_clock

    monkeypatch.setenv("JARVIS_VIDEO_PROVIDER", "deepinfra")
    monkeypatch.setenv("DEEPINFRA_API_KEY", "di-fixture-key")
    monkeypatch.setattr(video_clock, "MAX_SLEEP_SECONDS", 0.01)
    video.state.provider = "deepinfra-cdn"
    video.state.offhost = 0
    video.state.delivery = ("data:video/mp4;base64," + base64.b64encode(MP4).decode()
                            if delivery == "data-uri" else delivery)
    task = await _approve(video, video.runtime.submit(
        {"prompt": "rain", "model": "Wan-AI/Wan2.6-T2V", "duration": 4}, "user"))
    assert task.result["status"] == "ok", task.result
    assert video.state.offhost == 0          # never dialled off the API host


@pytest.mark.parametrize("brand, mime", [(b"iso5", "video/mp4"), (b"iso6", "video/mp4"), (b"qt  ", "video/quicktime")])
def test_fragmented_mp4_and_quicktime_brands_are_recognized(brand, mime):
    from agents.core.artifact_store import sniff

    assert sniff(b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 20) == mime


def test_the_video_choice_routes_are_gated_by_managed_configuration(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import managed_scope

    def pinned(name):
        raise managed_scope.ManagedRefused(f"{name} is pinned", names=[name], source="managed.env")

    monkeypatch.setattr(managed_scope, "check_env_write", pinned)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "admin-token")
    client = TestClient(web.app)
    headers = {"X-Admin-Token": "admin-token", "Content-Type": "application/json"}
    off = client.delete("/api/admin/integrations/video-choice", headers=headers)
    use = client.post("/api/admin/integrations/video.fal/use", headers=headers,
                      json={"acknowledge_training": True, "confirm_expensive": True})
    assert off.status_code == 409 and use.status_code == 409


def test_integrations_catalog_lists_the_video_providers_with_their_facts(monkeypatch):
    from agents.core import integrations_catalog

    monkeypatch.delenv("JARVIS_VIDEO_PROVIDER", raising=False)
    rows = {r["id"]: r for r in integrations_catalog.listing()["integrations"]}
    for name, key in (("fal", "FAL_KEY"), ("xai", "XAI_API_KEY"), ("deepinfra", "DEEPINFRA_API_KEY")):
        row = rows[f"video.{name}"]
        assert row["kind"] == "video" and row["origin"] == "hermes"
        assert row["key"]["primary"] == key and row["selectable"] is True
        assert row["selected"] is False
        assert "per second" in row["facts"]["price_note"]
    assert "FAL_KEY" in integrations_catalog.managed_keys()


def test_integrations_use_asks_consent_and_stores_the_choice(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import integration_keys
    from agents.core.routers import integrations_setup

    monkeypatch.delenv("JARVIS_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("NERVA_VIDEO_PROVIDER", raising=False)
    monkeypatch.setenv("FAL_KEY", "fal-fixture-key")
    monkeypatch.setattr(integration_keys, "_store_path", lambda: tmp_path / "secrets.enc")
    audits = []

    async def audit(preview, action, *, required=False):
        audits.append(action)

    monkeypatch.setattr(integrations_setup, "_audit", audit)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "admin-token")
    client = TestClient(web.app)
    headers = {"X-Admin-Token": "admin-token", "Content-Type": "application/json"}
    first = client.post("/api/admin/integrations/video.fal/use", headers=headers, json={})
    assert first.status_code == 409 and set(first.json()["needs"]) == {"acknowledge_training", "confirm_expensive"}
    ok = client.post("/api/admin/integrations/video.fal/use", headers=headers,
                     json={"acknowledge_training": True, "confirm_expensive": True})
    assert ok.status_code == 200, ok.text
    assert audits == ["video_provider_consent"]
    from agents.core.creative import video_providers as vp

    assert vp.chosen() == "fal"
    off = client.delete("/api/admin/integrations/video-choice", headers=headers)
    assert off.status_code == 200 and vp.chosen() == ""
    integration_keys.reset_for_tests()
