"""model-setup slice — hardware-tiered local-model recommendation + governed Ollama pull.

Everything here is hermetic: Ollama is an ``httpx.MockTransport``, the kernel is a
fake authorizer, the pull runs through an injected ``spawn`` that awaits inline.

Claims pinned:
  * the tier table maps measured VRAM to a rung and NEVER upgrades an unmeasured
    GPU (cpu-only), and every recommendation carries the "not benchmarked" basis;
  * presence + pull refuse any non-loopback Ollama URL by name;
  * the size cap is enforced from the stream's own layer totals (``model_too_large``);
  * the route refuses ``model_pull_disabled`` with the flag unset — and touches
    no transport;
  * a kernel DENY blocks the pull before any byte moves; a GRANT starts the job;
  * the routes are user-guarded (the guard can refuse).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.capability_actions import CapabilityActionAPI, PerformContext
from agents.core.kernel import Decision, Verdict
from agents.core.llm import model_setup as ms
from agents.core.routers import model_setup as routes
from agents.core.routers._deps import user_guard

OLLAMA = "http://127.0.0.1:11434"


def _gpu(vram=None, measured=False, name="none", kind=None, **extra):
    kind = kind or ("none" if not measured else "nvidia")
    return {"name": name, "kind": kind, "vram_total_mb": vram, "vram_used_mb": None,
            "load_pct": None, "measured": measured, **extra}


def _hw(gpu=None, threads=8, ram=32.0):
    return {"gpu": gpu or _gpu(), "cpu_threads": threads, "ram_total_gb": ram}


# ── the tier table ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("vram,expected_tier,expected_model", [
    (4096, "cpu-only", "qwen2.5:3b"),          # a 4 GB card cannot hold the 7b rung
    (8192, "8gb", "qwen2.5:7b"),
    (12288, "12-16gb", "qwen2.5:14b"),
    (16384, "12-16gb", "qwen2.5:14b"),
    (24576, "24gb+", "gemma-4-31b-a4b"),
    (49152, "24gb+", "gemma-4-31b-a4b"),
])
def test_tier_table_maps_measured_vram(vram, expected_tier, expected_model):
    rec = ms.recommend_model(_hw(_gpu(vram, True, "card")))
    assert (rec["tier"], rec["model"]) == (expected_tier, expected_model)
    assert rec["basis"] == "spec-based, not benchmarked"
    assert rec["vram_mb"] == vram


def test_no_gpu_measured_is_cpu_only_never_upgraded():
    rec = ms.recommend_model(_hw(_gpu(), threads=32, ram=192.0))
    assert rec["tier"] == "cpu-only" and rec["model"] == "qwen2.5:3b"
    assert rec["vram_mb"] is None
    assert any("never assumed" in r for r in rec["reasons"])
    # an unmeasured dict that still carries a number must not be credited
    lying = _gpu(24576, False, "ghost")
    assert ms.recommend_model(_hw(lying))["tier"] == "cpu-only"
    assert ms.recommend_model(None)["tier"] == "cpu-only"


def test_apple_unified_memory_is_named_in_the_reasons():
    gpu = _gpu(24576, True, "Apple Silicon (unified memory)", kind="apple",
               note="unified memory: GPU budget assumed at 75% of 32768 MB RAM")
    rec = ms.recommend_model(_hw(gpu))
    assert rec["tier"] == "24gb+" and rec["gpu_kind"] == "apple"
    assert any("assumed at 75%" in r for r in rec["reasons"])


def test_low_ram_cpu_only_warns_and_tier_table_is_exposed():
    rec = ms.recommend_model(_hw(_gpu(), ram=4.0))
    assert any("page" in r for r in rec["reasons"])
    table = ms.tier_table()
    assert [t["tier"] for t in table] == ["cpu-only", "8gb", "12-16gb", "24gb+"]
    assert all(t["approx_gb"] > 0 for t in table)


# ── loopback + contract ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url,ok", [
    ("http://localhost:11434", True),
    ("http://127.0.0.1:11434", True),
    ("http://[::1]:11434", True),
    ("http://192.168.1.20:11434", False),
    ("http://ollama.example.com", False),
    ("ftp://127.0.0.1", False),
    ("", False),
])
def test_loopback_only(url, ok):
    assert ms.is_loopback_url(url) is ok


@pytest.mark.parametrize("tag,ok", [
    ("qwen2.5:7b", True), ("library/qwen2.5:7b-instruct-q4_K_M", True), ("gemma-4-31b-a4b", True),
    ("../etc", False), ("/abs", False), ("-flag", False), ("a//b", False), ("x:", False),
    ("a:b:c", False), ("bad tag!", False), ("", False), (None, False),
])
def test_valid_model_tag_is_a_tag_not_a_path(tag, ok):
    assert ms.valid_model_tag(tag) is ok


def test_contract_denies_bad_tag_lan_url_and_bad_cap():
    good = {"model": "qwen2.5:7b", "url": OLLAMA, "max_bytes": 10}
    assert ms.MODEL_PULL_CONTRACT.evaluate(good).admissible
    assert ms.MODEL_PULL_CONTRACT.evaluate({**good, "model": "../etc"}).reason == "invalid_model_tag"
    assert ms.MODEL_PULL_CONTRACT.evaluate({**good, "url": "http://10.0.0.5"}).reason == "ollama_url_not_loopback"
    assert ms.MODEL_PULL_CONTRACT.evaluate({**good, "max_bytes": 0}).reason == "invalid_max_bytes"
    assert ms.MODEL_PULL_CONTRACT.evaluate({"url": OLLAMA, "max_bytes": 1}).reason == "missing_field:model"


def test_manifest_is_valid_and_reversible():
    """The pull's manifest lives with every other action kind — one registry, no shim."""
    from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS

    manifest = ACTION_CAPABILITY_MANIFESTS["model.pull"]
    assert manifest.id == ms.MODEL_PULL_CAPABILITY_ID == "action:model.pull"
    assert manifest.action_kind == ms.MODEL_PULL_KIND
    assert manifest.risk == "reversible"
    assert manifest.rollback.mode == "compensate"
    assert manifest.rollback.handler_ref.endswith(":ollama_delete")
    assert manifest.contract_ref == "agents.core.llm.model_setup:MODEL_PULL_CONTRACT"
    rows = list(ACTION_CAPABILITY_MANIFESTS.values())
    assert sum(1 for r in rows if r.id == "action:model.pull") == 1


# ── Ollama transport (MockTransport) ─────────────────────────────────────────

def _ndjson(events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _client(handler):
    return httpx.AsyncClient(base_url=OLLAMA, transport=httpx.MockTransport(handler))


def _tags_handler(models=("qwen2.5:7b",), status=200):
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(status, json={"models": [{"name": m} for m in models]})
    return handler


async def test_ollama_present_reads_tags_and_refuses_lan():
    async with _client(_tags_handler(("qwen2.5:7b", "llama3:8b"))) as c:
        got = await ms.ollama_present(OLLAMA, client=c)
    assert got == {"present": True, "url": OLLAMA, "models": ["llama3:8b", "qwen2.5:7b"], "reason": ""}
    lan = await ms.ollama_present("http://192.168.1.9:11434")
    assert lan["present"] is False and lan["reason"] == "ollama_url_not_loopback"

    def boom(request):
        raise httpx.ConnectError("refused")
    async with _client(boom) as c:
        down = await ms.ollama_present(OLLAMA, client=c)
    assert down["present"] is False and down["reason"] == "ollama_unreachable"


async def test_ollama_pull_streams_progress_to_success():
    seen = []
    events = [
        {"status": "pulling manifest"},
        {"status": "pulling a", "digest": "sha256:a", "total": 1000, "completed": 100},
        {"status": "pulling a", "digest": "sha256:a", "total": 1000, "completed": 1000},
        {"status": "pulling b", "digest": "sha256:b", "total": 500, "completed": 500},
        {"status": "verifying sha256 digest"},
        {"status": "success"},
    ]

    def handler(request):
        assert request.url.path == "/api/pull" and request.method == "POST"
        assert json.loads(request.content) == {"model": "qwen2.5:7b", "stream": True}
        return httpx.Response(200, content=_ndjson(events).encode())

    async with _client(handler) as c:
        got = await ms.ollama_pull(OLLAMA, "qwen2.5:7b", progress_cb=seen.append,
                                  max_bytes=10_000, client=c)
    assert got["ok"] is True and got["status"] == "success"
    assert got["bytes_total"] == 1500 and got["bytes_completed"] == 1500
    assert seen[1] == {"status": "pulling a", "bytes_total": 1000, "bytes_completed": 100}
    assert seen[-1]["status"] == "success"


async def test_ollama_pull_size_cap_is_enforced_from_layer_totals():
    events = [
        {"status": "pulling a", "digest": "sha256:a", "total": 3_000, "completed": 10},
        {"status": "pulling b", "digest": "sha256:b", "total": 3_000, "completed": 0},
        {"status": "success"},
    ]

    def handler(request):
        return httpx.Response(200, content=_ndjson(events).encode())

    async with _client(handler) as c:
        got = await ms.ollama_pull(OLLAMA, "qwen2.5:14b", max_bytes=5_000, client=c)
    assert got["ok"] is False and got["reason"] == "model_too_large"
    assert got["bytes_total"] == 6_000 and got["max_bytes"] == 5_000
    # the same digest repeated is one layer, not counted twice
    events2 = [
        {"status": "pulling a", "digest": "sha256:a", "total": 3_000, "completed": 10},
        {"status": "pulling a", "digest": "sha256:a", "total": 3_000, "completed": 3_000},
        {"status": "success"},
    ]
    async with _client(lambda r: httpx.Response(200, content=_ndjson(events2).encode())) as c:
        assert (await ms.ollama_pull(OLLAMA, "qwen2.5:14b", max_bytes=5_000, client=c))["ok"]


async def test_ollama_pull_refuses_before_any_transport_on_bad_input():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=b"")

    async with _client(handler) as c:
        assert (await ms.ollama_pull(OLLAMA, "bad tag!", client=c))["reason"] == "invalid_model_tag"
        assert (await ms.ollama_pull("http://10.1.1.1", "qwen2.5:7b", client=c))["reason"] == "ollama_url_not_loopback"
        assert (await ms.ollama_pull(OLLAMA, "qwen2.5:7b", max_bytes=-1, client=c))["reason"] == "invalid_max_bytes"
    assert calls == []


async def test_ollama_pull_error_line_and_http_error_are_named():
    async with _client(lambda r: httpx.Response(200, content=_ndjson([{"error": "pull model manifest: file does not exist"}]).encode())) as c:
        got = await ms.ollama_pull(OLLAMA, "nope:1b", client=c)
    assert got["ok"] is False and got["reason"] == "ollama_error"
    assert "does not exist" in got["detail"]
    async with _client(lambda r: httpx.Response(404, content=b"")) as c:
        assert (await ms.ollama_pull(OLLAMA, "nope:1b", client=c))["reason"] == "ollama_http_404"
    async with _client(lambda r: httpx.Response(200, content=_ndjson([{"status": "pulling"}]).encode())) as c:
        assert (await ms.ollama_pull(OLLAMA, "x:1b", client=c))["reason"] == "ollama_stream_ended"


async def test_ollama_delete_is_the_compensate_path():
    def handler(request):
        assert request.method == "DELETE" and request.url.path == "/api/delete"
        assert json.loads(request.content) == {"model": "qwen2.5:7b"}
        return httpx.Response(200, json={})
    async with _client(handler) as c:
        assert (await ms.ollama_delete(OLLAMA, "qwen2.5:7b", client=c)) == {"ok": True, "model": "qwen2.5:7b", "deleted": True}
    assert (await ms.ollama_delete("http://10.0.0.1", "qwen2.5:7b"))["reason"] == "ollama_url_not_loopback"


# ── the service + the facade ─────────────────────────────────────────────────

class _FakeOllama:
    """Presence + pull seams in one object; records what the service asked for."""

    def __init__(self, present=True, models=(), pull_result=None):
        self.present = present
        self.models = list(models)
        self.pull_result = pull_result or {"ok": True, "bytes_total": 42, "bytes_completed": 42}
        self.pulls = []

    async def presence(self, url, **_):
        return {"present": self.present, "url": url, "models": list(self.models),
                "reason": "" if self.present else "ollama_unreachable"}

    async def pull(self, url, model, *, progress_cb=None, max_bytes=None, **_):
        self.pulls.append({"url": url, "model": model, "max_bytes": max_bytes})
        if progress_cb:
            progress_cb({"status": "pulling", "bytes_total": 42, "bytes_completed": 21})
        return dict(self.pull_result)


async def _inline_spawn(coro):
    await coro
    return None


def _service(fake, **kw):
    clock = iter(range(100, 200))
    return ms.ModelSetupService(
        ollama_url=OLLAMA, max_gb=kw.pop("max_gb", 20),
        hardware_fn=kw.pop("hardware_fn", lambda: _hw(_gpu(8192, True, "card"))),
        present_fn=fake.presence, pull_fn=fake.pull, spawn=kw.pop("spawn", _inline_spawn),
        clock=lambda: float(next(clock)), **kw)


async def test_plan_reports_recommendation_presence_and_flag():
    fake = _FakeOllama(models=["qwen2.5:7b"])
    plan = await _service(fake).plan(enabled=False)
    assert plan["recommendation"]["model"] == "qwen2.5:7b"
    assert plan["recommended_installed"] is True
    assert plan["ollama"]["present"] is True
    assert plan["pull"] == {"enabled": False, "max_gb": 20.0, "job": None,
                            "hint": "set JARVIS_MODEL_PULL=1 to allow governed pulls"}
    assert plan["basis"] == "spec-based, not benchmarked"
    assert [t["tier"] for t in plan["tiers"]][0] == "cpu-only"


async def test_handle_pull_runs_the_job_and_reports_it():
    fake = _FakeOllama()
    svc = _service(fake)
    out = await svc.handle_pull({"model": "qwen2.5:7b"})
    assert out["ok"] and out["started"] is True
    assert fake.pulls == [{"url": OLLAMA, "model": "qwen2.5:7b", "max_bytes": 20 * 1024 ** 3}]
    job = svc.job_snapshot()
    assert job["status"] == "done" and job["bytes_total"] == 42 and job["finished_at"] == 101.0
    # a failed pull keeps the reason on the job
    fake2 = _FakeOllama(pull_result={"ok": False, "reason": "model_too_large"})
    svc2 = _service(fake2)
    await svc2.handle_pull({"model": "qwen2.5:7b"})
    assert svc2.job_snapshot()["status"] == "failed"
    assert svc2.job_snapshot()["reason"] == "model_too_large"


async def test_handle_pull_refuses_honestly_without_touching_the_transport():
    fake = _FakeOllama(present=False)
    svc = _service(fake)
    assert (await svc.handle_pull({"model": "../x"}))["reason"] == "invalid_model_tag"
    assert (await svc.handle_pull({"model": "qwen2.5:7b", "url": "http://10.0.0.2"}))["reason"] == "ollama_url_not_loopback"
    assert (await svc.handle_pull({"model": "qwen2.5:7b"}))["reason"] == "ollama_unreachable"
    assert fake.pulls == []
    have = _FakeOllama(models=["qwen2.5:7b"])
    out = await _service(have).handle_pull({"model": "qwen2.5:7b"})
    assert out == {"ok": True, "already_installed": True, "model": "qwen2.5:7b", "started": False}
    assert have.pulls == []


async def test_only_one_pull_at_a_time():
    fake = _FakeOllama()

    async def never_spawn(coro):
        coro.close()          # leave the job "running" forever
        return None

    svc = _service(fake, spawn=never_spawn)
    assert (await svc.handle_pull({"model": "qwen2.5:7b"}))["started"] is True
    again = await svc.handle_pull({"model": "qwen2.5:3b"})
    assert again["ok"] is False and again["reason"] == "pull_in_progress"


def _facade(svc, verdict, reason=""):
    seen = []

    def authorizer(action, capability=None):
        seen.append(action)
        return Decision(verdict, reason=reason)

    from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS

    api = CapabilityActionAPI(authorizer=authorizer,
                              manifests=list(ACTION_CAPABILITY_MANIFESTS.values()))
    api.register(ms.MODEL_PULL_CAPABILITY_ID, svc.handle_pull)
    return api, seen


@pytest.fixture
def facade_on(monkeypatch):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")


async def test_kernel_deny_blocks_the_pull(facade_on):
    fake = _FakeOllama()
    api, seen = _facade(_service(fake), Verdict.DENY, "kill switch engaged")
    res = await api.perform(ms.MODEL_PULL_CAPABILITY_ID,
                            {"model": "qwen2.5:7b", "url": OLLAMA, "max_bytes": 10},
                            PerformContext(agent="jarvis", title="t", origin="user"))
    assert res.status == "refused" and res.reason == "kill switch engaged"
    assert fake.pulls == []
    assert seen[0].kind == "model.pull" and seen[0].payload["model"] == "qwen2.5:7b"


async def test_kernel_grant_starts_the_pull_and_queue_holds_it(facade_on):
    fake = _FakeOllama()
    api, _ = _facade(_service(fake), Verdict.GRANT)
    res = await api.perform(ms.MODEL_PULL_CAPABILITY_ID,
                            {"model": "qwen2.5:7b", "url": OLLAMA, "max_bytes": 10 ** 9})
    assert res.status == "completed" and res.output["started"] is True
    assert [p["model"] for p in fake.pulls] == ["qwen2.5:7b"]
    queued = _FakeOllama()
    api2, _ = _facade(_service(queued), Verdict.QUEUE, "ask")
    res2 = await api2.perform(ms.MODEL_PULL_CAPABILITY_ID, {"model": "qwen2.5:7b", "url": OLLAMA, "max_bytes": 5})
    assert res2.status == "queued" and queued.pulls == []


async def test_facade_off_never_reaches_the_handler(monkeypatch):
    monkeypatch.delenv("JARVIS_UNIFIED_ACTION_API", raising=False)
    fake = _FakeOllama()
    api, seen = _facade(_service(fake), Verdict.GRANT)
    res = await api.perform(ms.MODEL_PULL_CAPABILITY_ID, {"model": "qwen2.5:7b"})
    assert res.status == "disabled" and res.reason == "unified_action_api_disabled"
    assert fake.pulls == [] and seen == []


# ── the routes ───────────────────────────────────────────────────────────────

@pytest.fixture
def app(monkeypatch):
    fake = _FakeOllama()
    svc = _service(fake)
    monkeypatch.setattr(routes, "_service", svc)
    application = FastAPI()
    application.include_router(routes.router)
    application.dependency_overrides[user_guard] = lambda: None
    application.state.fake = fake
    application.state.svc = svc
    return application


def _grant_api(monkeypatch, app, verdict, reason=""):
    def build(service):
        api, _ = _facade(service, verdict, reason)
        return api
    monkeypatch.setattr(routes, "_build_api", build)


def test_routes_are_user_guarded(monkeypatch):
    svc = _service(_FakeOllama())
    monkeypatch.setattr(routes, "_service", svc)
    application = FastAPI()
    application.include_router(routes.router)

    async def _deny():
        raise HTTPException(status_code=401, detail="user token required")

    application.dependency_overrides[user_guard] = _deny
    c = TestClient(application)
    assert c.get("/api/onboarding/model-plan").status_code == 401
    assert c.post("/api/onboarding/model-pull", json={}).status_code == 401


def test_model_plan_route_shape(app, monkeypatch):
    monkeypatch.delenv("JARVIS_MODEL_PULL", raising=False)
    r = TestClient(app).get("/api/onboarding/model-plan")
    assert r.status_code == 200
    assert r.headers["cache-control"].startswith("no-cache")
    body = r.json()
    assert body["recommendation"]["model"] == "qwen2.5:7b"
    assert body["recommendation"]["basis"] == "spec-based, not benchmarked"
    assert body["pull"]["enabled"] is False and body["pull"]["job"] is None
    assert body["hardware"]["gpu"]["vram_total_mb"] == 8192


def test_model_pull_refuses_when_flag_unset(app, monkeypatch):
    monkeypatch.delenv("JARVIS_MODEL_PULL", raising=False)
    _grant_api(monkeypatch, app, Verdict.GRANT)
    r = TestClient(app).post("/api/onboarding/model-pull", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["enabled"] is False
    assert body["reason"] == "model_pull_disabled"
    assert "JARVIS_MODEL_PULL" in body["hint"]
    assert app.state.fake.pulls == []


def test_model_pull_kernel_deny_is_a_403(app, monkeypatch, facade_on):
    monkeypatch.setenv("JARVIS_MODEL_PULL", "1")
    _grant_api(monkeypatch, app, Verdict.DENY, "budget: interrupts exhausted")
    r = TestClient(app).post("/api/onboarding/model-pull", json={"model": "qwen2.5:14b"})
    assert r.status_code == 403
    assert r.json()["status"] == "refused"
    assert r.json()["reason"] == "budget: interrupts exhausted"
    assert app.state.fake.pulls == []


def test_model_pull_grant_pulls_the_recommendation_by_default(app, monkeypatch, facade_on):
    monkeypatch.setenv("JARVIS_MODEL_PULL", "1")
    _grant_api(monkeypatch, app, Verdict.GRANT)
    c = TestClient(app)
    r = c.post("/api/onboarding/model-pull", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["status"] == "completed" and body["model"] == "qwen2.5:7b"
    assert body["output"]["started"] is True
    assert app.state.fake.pulls[0]["model"] == "qwen2.5:7b"
    assert app.state.fake.pulls[0]["max_bytes"] == 20 * 1024 ** 3
    plan = c.get("/api/onboarding/model-plan").json()
    assert plan["pull"]["job"]["status"] == "done"
    assert plan["pull"]["job"]["model"] == "qwen2.5:7b"


def test_model_pull_queue_is_a_202_and_bad_tag_a_422(app, monkeypatch, facade_on):
    monkeypatch.setenv("JARVIS_MODEL_PULL", "1")
    _grant_api(monkeypatch, app, Verdict.QUEUE, "ask")
    c = TestClient(app)
    assert c.post("/api/onboarding/model-pull", json={"model": "qwen2.5:7b"}).status_code == 202
    r = c.post("/api/onboarding/model-pull", json={"model": "bad tag!"})
    assert r.status_code == 422 and r.json()["reason"] == "invalid_model_tag"
    assert app.state.fake.pulls == []


def test_model_pull_without_kernel_is_refused_not_executed(app, monkeypatch, facade_on):
    """The real `_build_api`: no orchestrator → no authorizer → kernel_unavailable."""
    monkeypatch.setenv("JARVIS_MODEL_PULL", "1")
    from agents.core import app_state

    monkeypatch.setattr(app_state, "get_orch", lambda: None)
    r = TestClient(app).post("/api/onboarding/model-pull", json={"model": "qwen2.5:7b"})
    assert r.status_code == 403 and r.json()["reason"] == "kernel_unavailable"
    assert app.state.fake.pulls == []


def test_build_api_binds_the_kernel_hook_from_the_orchestrator(monkeypatch):
    from agents.core import app_state
    from agents.core.kernel import binding

    seen = {}

    def fake_kernel(orch, **_):
        seen["orch"] = orch
        return lambda action, capability=None: Decision(Verdict.GRANT)

    orch = SimpleNamespace(autonomy=SimpleNamespace(policy=object()))
    monkeypatch.setattr(app_state, "get_orch", lambda: orch)
    monkeypatch.setattr(binding, "make_action_kernel", fake_kernel)
    api = routes._build_api(_service(_FakeOllama()))
    assert seen["orch"] is orch
    assert api._authorizer is not None
    assert ms.MODEL_PULL_CAPABILITY_ID in api._bindings


def test_settings_reads_are_live_and_default_safe(monkeypatch):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "get_value", lambda cat, key, default=None: default)
    assert routes._ollama_url() == ms.DEFAULT_OLLAMA_URL
    assert routes._max_gb() == 20
    monkeypatch.setattr(settings_db, "get_value",
                        lambda cat, key, default=None: {"ollama_url": "http://localhost:11500", "model_pull_max_gb": 5}[key])
    svc = ms.ModelSetupService(ollama_url=routes._ollama_url, max_gb=routes._max_gb)
    assert svc.ollama_url() == "http://localhost:11500"
    assert svc.max_bytes() == 5 * 1024 ** 3
    assert ms.ModelSetupService(max_gb="junk").max_bytes() == 20 * 1024 ** 3


def test_no_test_leaks_the_flag():
    assert os.environ.get("JARVIS_MODEL_PULL") is None
