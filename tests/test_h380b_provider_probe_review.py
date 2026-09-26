"""H380 review round — the cloud-key probe proves the key, and only the key it means.

- OpenRouter's model list answers anyone, so its key is read at ``/key`` (F1);
- ``check all providers`` sends ``OPENAI_API_KEY`` to api.openai.com only when it is an
  OpenAI key: beside an ``OPENAI_BASE_URL`` on another host it is that gateway's (F2);
- Gemini and xAI refuse a bad key with a 400 that names it (F3);
- a 404/405 never evaluated the key, so it proves nothing (F4);
- the key is the one the router reads (pools only where the router has one) (F5);
- a key the shared 429 guard holds is ``rate_limited``, briefly (F6, F9);
- concurrent callers share one request (F7); the command center waits a bounded time (F8);
- a transient verdict neither lasts five minutes nor sends an owner to first run (F9);
- the probe takes the backend's network path (F10); the hint names the provider (F11);
- a changed base URL is probed afresh (F12).
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm import provider_probe  # noqa: E402
from agents.core.llm.egress import llm_async_client  # noqa: E402
from agents.core.llm.providers import get_profile  # noqa: E402

KEY = "sk-test-SECRET-4c3b2a"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    provider_probe.reset()
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS", "GEMINI_API_KEY", "GEMINI_API_KEYS",
                "OPENROUTER_API_KEY", "OPENROUTER_API_KEYS", "OPENROUTER_BASE_URL", "XAI_API_KEY",
                "XAI_API_KEYS", "OPENAI_API_KEY", "OPENAI_API_KEYS", "OPENAI_BASE_URL"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    yield
    provider_probe.reset()


class _Hub:
    """A mock provider behind the real ``llm_async_client``; ``answer(request)`` replies."""

    def __init__(self, answer=None, delay=0.0):
        self.answer = answer or (lambda request: httpx.Response(200, json={"data": [{}]}))
        self.delay, self.requests, self.clients = delay, [], []

    async def handler(self, request):
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.answer(request)

    def factory(self, backend, **kwargs):
        client = llm_async_client(backend, transport=httpx.MockTransport(self.handler), **kwargs)
        self.clients.append(client)
        return client


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _probe(provider, hub, **kwargs):
    return asyncio.run(provider_probe.probe(provider, client_factory=hub.factory, **kwargs))


# ── F1: OpenRouter's key, not its public list ────────────────────────────────────

def _openrouter(request):
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{}, {}]})           # answers with any key, or none
    good = request.headers.get("authorization") == "Bearer good-key"
    return httpx.Response(200 if good else 401, json={"data": {"label": "x"}} if good else {"error": {}})


def test_openrouter_is_asked_about_its_key_not_its_public_model_list():
    url, headers = provider_probe.request_for(get_profile("openrouter"), KEY)
    assert url == "https://openrouter.ai/api/v1/key" and headers == {"Authorization": f"Bearer {KEY}"}
    url, _ = provider_probe.request_for(get_profile("openrouter"), KEY,
                                        environ={"OPENROUTER_BASE_URL": "https://proxy.example/v1/"})
    assert url == "https://proxy.example/v1/key"
    hub = _Hub(_openrouter)
    assert _probe("openrouter", hub, key="made-up")["verdict"] == "auth_failed"
    provider_probe.reset()
    assert _probe("openrouter", hub, key="good-key")["verdict"] == "ok"
    assert [r.url.path for r in hub.requests] == ["/api/v1/key", "/api/v1/key"]


# ── F2: a gateway's key stays with the gateway ───────────────────────────────────

def test_check_all_keeps_a_gateway_key_away_from_api_openai_com(monkeypatch):
    from agents.core import settings_db

    monkeypatch.setenv("OPENAI_API_KEY", "gsk_GROQKEY")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings_db, "get_value", lambda section, key, default=None: "openai-compatible")
    hub = _Hub()
    results = asyncio.run(provider_probe.probe_all(client_factory=hub.factory))
    assert [r.url.host for r in hub.requests] == ["api.groq.com"]
    assert "openai-responses" not in {r["provider"] for r in results}
    assert {r["provider"]: r["verdict"] for r in results}["openai-compatible"] == "ok"


def test_check_all_asks_openai_when_the_key_is_openais(monkeypatch):
    from agents.core import settings_db

    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    hub = _Hub()
    asyncio.run(provider_probe.probe_all(client_factory=hub.factory))       # no gateway: both are OpenAI
    assert [r.url.host for r in hub.requests] == ["api.openai.com", "api.openai.com"]
    provider_probe.reset()
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings_db, "get_value", lambda section, key, default=None: "openai-responses")
    hub = _Hub()
    asyncio.run(provider_probe.probe_all(client_factory=hub.factory))       # the owner chose OpenAI
    assert sorted(r.url.host for r in hub.requests) == ["api.groq.com", "api.openai.com"]


# ── F3: a bad key refused with a 400 ─────────────────────────────────────────────

GEMINI_BAD = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                        "status": "INVALID_ARGUMENT", "details": [{
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID",
                            "domain": "googleapis.com"}]}}
GEMINI_EXPIRED = {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                            "details": [{"reason": "API_KEY_EXPIRED"}]}}
XAI_BAD = {"code": "Client specified an invalid argument",
           "error": "Incorrect API key provided: sk***7d. You can obtain an API key from https://console.x.ai."}
OTHER_400 = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "details": [{"reason": "OTHER"}]}}


@pytest.mark.parametrize("provider,body,verdict", [
    ("gemini", GEMINI_BAD, "auth_failed"), ("gemini", GEMINI_EXPIRED, "auth_failed"),
    ("xai", XAI_BAD, "auth_failed"), ("gemini", OTHER_400, "error"), ("xai", {"error": "bad"}, "error"),
    ("gemini", "not json", "error"),
])
def test_a_400_that_names_a_bad_key_is_a_rejected_key(provider, body, verdict):
    reply = (lambda r: httpx.Response(400, text=body)) if isinstance(body, str) else (
        lambda r: httpx.Response(400, json=body))
    result = _probe(provider, _Hub(reply), key=KEY)
    assert (result["verdict"], result["status_code"], result["working"]) == (verdict, 400, False)
    assert "API_KEY" not in repr(result) and "Incorrect" not in repr(result)     # the body stays inside


# ── F4: a missing listing proves nothing ─────────────────────────────────────────

@pytest.mark.parametrize("status", [404, 405])
def test_a_missing_listing_does_not_prove_the_key(status):
    result = _probe("openai-compatible", _Hub(lambda r: httpx.Response(status)), key=KEY,
                    environ={"OPENAI_BASE_URL": "https://api.openai.com"})        # /v1 missing
    assert result["verdict"] == "no_listing" and result["working"] is False
    assert "no_listing" not in provider_probe.WORKING


# ── F5: the key the router reads ─────────────────────────────────────────────────

def test_the_key_is_read_the_way_the_router_reads_it(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEYS", "key-one key-two")                 # a whitespace pool
    assert provider_probe.configured_key(get_profile("anthropic")) == "key-one"
    assert provider_probe.configured_key(get_profile("gemini"), environ={"GEMINI_API_KEYS": "g1\tg2"}) == "g1"
    # Only Anthropic and Gemini have a rotation pool: OPENROUTER_API_KEYS is never read.
    monkeypatch.setenv("OPENROUTER_API_KEY", "single")
    monkeypatch.setenv("OPENROUTER_API_KEYS", "leftover")
    assert provider_probe.configured_key(get_profile("openrouter")) == "single"
    monkeypatch.setenv("XAI_API_KEYS", "leftover")
    assert provider_probe.configured_key(get_profile("xai")) == ""


def test_the_command_center_asks_with_the_compatible_backends_own_key(monkeypatch):
    from agents.core.routers import onboarding

    seen = []

    async def fake_probe(provider, *, key=None, **kw):
        seen.append((provider, key))
        return {"provider": provider, "verdict": "ok"}

    monkeypatch.setattr(provider_probe, "probe", fake_probe)
    router = SimpleNamespace(_compatible_backend=SimpleNamespace(api_key="route-key"))
    asyncio.run(onboarding._cloud_probe(router, "openrouter"))
    assert seen == [("openrouter", "route-key")]


# ── F6 / F9: the shared 429 guard, and how long a transient verdict lasts ────────

def test_a_key_held_by_the_shared_429_guard_is_rate_limited_for_the_hold():
    from agents.core.llm import quota

    fp = hashlib.sha256(KEY.encode()).hexdigest()[:12]
    quota.get_store().block("anthropic", fp, 120)
    hub, clock = _Hub(), _Clock()
    held = _probe("anthropic", hub, key=KEY, clock=clock)
    assert (held["verdict"], held["status_code"], hub.requests) == ("rate_limited", None, [])
    clock.t += provider_probe.TRANSIENT_TTL_SECONDS - 1
    assert _probe("anthropic", hub, key=KEY, clock=clock)["cached"] is True
    clock.t += 1                                                  # a long hold: asked again, still held
    again = _probe("anthropic", hub, key=KEY, clock=clock)
    assert (again["verdict"], again["cached"], hub.requests) == ("rate_limited", False, [])
    provider_probe.reset()
    quota.get_store().block("anthropic", fp, 5)
    _probe("anthropic", hub, key=KEY, clock=clock)
    quota.get_store().block("anthropic", fp, 0)                                  # the hold lifts
    clock.t += 6                                                  # kept no longer than the 5 s hold
    assert _probe("anthropic", hub, key=KEY, clock=clock)["verdict"] == "ok" and len(hub.requests) == 1


@pytest.mark.parametrize("answer,verdict", [
    (lambda r: httpx.Response(503), "error"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")), "unreachable"),
])
def test_a_transient_verdict_is_asked_again_soon(answer, verdict):
    hub, clock = _Hub(answer), _Clock()
    assert _probe("gemini", hub, key=KEY, clock=clock)["verdict"] == verdict
    clock.t += provider_probe.TRANSIENT_TTL_SECONDS - 1
    assert _probe("gemini", hub, key=KEY, clock=clock)["cached"] is True
    clock.t += 1
    hub.answer = lambda r: httpx.Response(200, json={"models": []})
    assert _probe("gemini", hub, key=KEY, clock=clock)["verdict"] == "ok" and len(hub.requests) == 2
    assert provider_probe.TRANSIENT_TTL_SECONDS < provider_probe.TTL_SECONDS


def _snapshot_with(monkeypatch, verdict, status_code=None):
    from agents import web
    from agents.core.routers import onboarding

    class _Router:
        _claude_backend = None
        _compatible_backend = None
        _gemini_backend = object()
        _local_available = False
        _backend = None
        _backend_name = "none"
        name = "none"
        active_model = "gemini-2.5-flash"

        def select_backend(self, agent_id, prompt):
            return self._gemini_backend, "gemini-2.5-flash", "cloud-flash"

    async def inventory(**kw):
        return {"configured_model": None, "resident_models": [], "residency_state": "offline",
                "providers": [], "models": []}

    async def said(llm_router, provider):
        return {"provider": "gemini", "verdict": verdict, "status_code": status_code,
                "checked_at": 1.0, "cached": False}

    monkeypatch.setattr(onboarding, "get_local_model_inventory", inventory)
    monkeypatch.setattr(onboarding, "_cloud_probe", said)
    orch = SimpleNamespace(llm_router=_Router(), agents={"jarvis": object()}, channels={"web": object()},
                           plugins={}, _runtime_settings={}, get_setting=lambda key, default=None: default)
    monkeypatch.setattr(web, "orch", orch, raising=False)
    return asyncio.run(onboarding._model_snapshot())


@pytest.mark.parametrize("verdict,ready", [
    ("rate_limited", True), ("unreachable", None), ("error", None), ("no_listing", None),
    ("auth_failed", False), ("forbidden", False), ("refused", False), ("not_configured", False),
])
def test_only_a_refused_key_makes_the_route_not_runnable(monkeypatch, verdict, ready):
    from agents.core.routers import onboarding

    block = _snapshot_with(monkeypatch, verdict)
    assert (block["ready"], block["reason"]) == (ready, f"cloud_{verdict}")
    assert block["reason"] in onboarding.MODEL_READINESS_REASONS


# ── F7: one request for concurrent callers ───────────────────────────────────────

def test_concurrent_callers_share_one_request():
    hub, clock = _Hub(delay=0.02), _Clock()

    async def burst(force):
        return await asyncio.gather(*(
            provider_probe.probe("anthropic", key=KEY, force=force, client_factory=hub.factory, clock=clock)
            for _ in range(20)))

    cold = asyncio.run(burst(False))
    assert len(hub.requests) == 1 and {r["verdict"] for r in cold} == {"ok"}
    assert sum(1 for r in cold if not r["cached"]) == 1
    clock.t += provider_probe.MIN_INTERVAL_SECONDS
    asyncio.run(burst(True))
    assert len(hub.requests) == 2


# ── F8: the command center does not outwait doctor ─────────────────────────────

def test_the_command_center_waits_a_bounded_time_for_the_provider(monkeypatch):
    from agents.core.routers import onboarding
    from scripts import doctor

    budget = inspect.signature(doctor.check_runtime_resolves).parameters["timeout"].default
    assert budget / 2 >= onboarding.CLOUD_PROBE_WAIT_SECONDS          # well inside doctor's read

    async def slow(provider, **kw):
        await asyncio.sleep(5)
        return {"provider": provider, "verdict": "ok"}

    monkeypatch.setattr(provider_probe, "probe", slow)
    monkeypatch.setattr(onboarding, "CLOUD_PROBE_WAIT_SECONDS", 0.05)
    started = time.monotonic()
    result = asyncio.run(onboarding._cloud_probe(SimpleNamespace(), "claude"))
    assert time.monotonic() - started < 2
    assert result["verdict"] == "unreachable" and result["provider"] == "anthropic"


# ── F10: the backend's network path ──────────────────────────────────────────────

def test_the_probe_takes_the_backends_network_path(monkeypatch):
    from agents.core.llm.responses import ResponsesBackend
    from agents.core.llm.xai import XAIBackend

    backends = {"xai": XAIBackend("k"), "openai-responses": ResponsesBackend("k")}
    for provider, backend in backends.items():
        hub = _Hub()
        _probe(provider, hub, key=KEY)
        assert hub.clients[0].trust_env is backend.client.trust_env is False
    hub = _Hub()
    _probe("anthropic", hub, key=KEY)
    assert hub.clients[0].trust_env is True                     # the Anthropic backend keeps the default


# ── F11: the hint names the provider and what it said ───────────────────────────

def test_a_refused_cloud_key_is_not_called_a_missing_local_model(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import analytics_store
    from agents.core.routers import onboarding
    from agents.core.routers._deps import user_guard

    _snapshot_with(monkeypatch, "auth_failed", 400)
    analytics_store.initialize(":memory:")
    web.app.dependency_overrides[user_guard] = lambda: None
    monkeypatch.setattr(onboarding, "_starter_outcomes", lambda **kw: [])
    try:
        client = TestClient(web.app)
        body = client.get("/api/onboarding/command-center").json()
        wizard = client.get("/api/onboarding/wizard").json()
    finally:
        web.app.dependency_overrides.pop(user_guard, None)
        analytics_store.close()
    for hint in (body["wizard"]["hint"], wizard["hint"]):
        assert "Google Gemini" in hint and "API key" in hint and "HTTP 400" in hint
        assert "LM Studio" not in hint
    say_hello = next(a for a in body["first_actions"] if a["key"] == "say_hello")
    assert say_hello["reason"] != "model not loaded"


# ── F12: the base URL is part of the cached verdict ──────────────────────────────

def test_a_changed_base_url_is_probed_afresh():
    hub, clock = _Hub(), _Clock()
    for base in ("https://a.example/v1", "https://b.example/v1", "https://a.example/v1"):
        _probe("openrouter", hub, key=KEY, clock=clock, environ={"OPENROUTER_BASE_URL": base})
    assert [r.url.host for r in hub.requests] == ["a.example", "b.example"]
    assert provider_probe.last("openrouter", key=KEY, clock=clock,
                               environ={"OPENROUTER_BASE_URL": "https://c.example/v1"}) is None
