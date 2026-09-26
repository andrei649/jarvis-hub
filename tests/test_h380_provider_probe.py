"""H380 — prove that a configured cloud provider actually works, before a turn finds out.

One authenticated read of the provider's model list, through the egress-ledgered LLM
client, with the key the hub would use: ``ok`` / ``no_listing`` / ``auth_failed`` /
``forbidden`` / ``rate_limited`` / ``error`` / ``unreachable`` / ``refused`` /
``not_configured`` / ``not_cloud``. Cached per provider and key, a forced re-check
throttled, the key and the body never returned or logged. The admin route, the HUD's
Provider Check panel and the command-center model block (read by ``nerva doctor``) use it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
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

KEY = "sk-test-SECRET-9f8e7d"
BODY_SENTINEL = "PROVIDER-BODY-SENTINEL"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    provider_probe.reset()
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS", "GEMINI_API_KEY", "GEMINI_API_KEYS",
                "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "XAI_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    yield
    provider_probe.reset()


class _Hub:
    """A mock transport through the real ``llm_async_client`` (egress hook included)."""

    def __init__(self, status=200, body=None, exc=None):
        self.status, self.exc, self.requests = status, exc, []
        self.body = {"data": [{"id": "m1"}, {"id": "m2"}], "note": BODY_SENTINEL} if body is None else body

    def handler(self, request):
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        if isinstance(self.body, str):
            return httpx.Response(self.status, text=self.body)
        return httpx.Response(self.status, json=self.body)

    def factory(self, backend, **kwargs):
        return llm_async_client(backend, transport=httpx.MockTransport(self.handler), **kwargs)


def _probe(provider, hub, **kwargs):
    return asyncio.run(provider_probe.probe(provider, client_factory=hub.factory, **kwargs))


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ── what is sent ─────────────────────────────────────────────────────────────────

def test_the_request_per_provider_carries_the_key_only_in_a_header():
    url, headers = provider_probe.request_for(get_profile("anthropic"), KEY)
    assert url == "https://api.anthropic.com/v1/models"
    assert headers == {"x-api-key": KEY, "anthropic-version": provider_probe.ANTHROPIC_VERSION}
    url, headers = provider_probe.request_for(get_profile("gemini"), KEY)
    assert url == "https://generativelanguage.googleapis.com/v1beta/models" and headers == {"x-goog-api-key": KEY}
    url, headers = provider_probe.request_for(get_profile("openrouter"), KEY)
    assert url == "https://openrouter.ai/api/v1/models" and headers == {"Authorization": f"Bearer {KEY}"}
    url, _ = provider_probe.request_for(get_profile("openrouter"), KEY,
                                        environ={"OPENROUTER_BASE_URL": "https://proxy.example/v1/"})
    assert url == "https://proxy.example/v1/models"
    assert provider_probe.request_for(get_profile("xai"), KEY)[0] == "https://api.x.ai/v1/models"


def test_the_key_the_hub_would_use(monkeypatch):
    profile = get_profile("anthropic")
    assert provider_probe.configured_key(profile) == ""
    monkeypatch.setenv("ANTHROPIC_API_KEY", " single ")
    assert provider_probe.configured_key(profile) == "single"
    monkeypatch.setenv("ANTHROPIC_API_KEYS", " , pooled-1, pooled-2")
    assert provider_probe.configured_key(profile) == "pooled-1"
    assert provider_probe.configured_key(profile, environ={"ANTHROPIC_API_KEY": "e"}) == "e"
    assert provider_probe.configured_key(profile, environ={"ANTHROPIC_API_KEYS": "a\nb"}) == "a"
    assert provider_probe.configured_key(get_profile("ollama")) == ""


def test_the_probe_sends_one_read_and_counts_the_models():
    hub = _Hub()
    result = _probe("anthropic", hub, key=KEY)
    assert result["verdict"] == "ok" and result["working"] is True and result["models"] == 2
    assert result["status_code"] == 200 and result["provider"] == "anthropic" and result["cached"] is False
    (request,) = hub.requests
    assert request.method == "GET" and str(request.url) == "https://api.anthropic.com/v1/models"
    assert request.headers["x-api-key"] == KEY and request.content == b""


@pytest.mark.parametrize("body,models", [
    ({"models": [{}, {}, {}]}, 3), ([{}, {}], 2), ({"other": 1}, None), ("not json", None),
])
def test_the_model_count_reads_every_list_shape(body, models):
    assert _probe("gemini", _Hub(body=body), key=KEY)["models"] == models


@pytest.mark.parametrize("status,verdict,working", [
    (200, "ok", True), (204, "ok", True), (401, "auth_failed", False), (403, "forbidden", False),
    (404, "no_listing", True), (405, "no_listing", True), (429, "rate_limited", False),
    (500, "error", False), (302, "error", False),
])
def test_a_status_is_a_verdict(status, verdict, working):
    result = _probe("xai", _Hub(status=status), key=KEY)
    assert (result["verdict"], result["working"], result["status_code"]) == (verdict, working, status)
    if verdict == "no_listing":
        assert result["models"] == len(get_profile("xai").fallback_models) == 2
    elif verdict != "ok":
        assert result["models"] is None


@pytest.mark.parametrize("exc", [httpx.ConnectError("no route"), httpx.ReadTimeout("slow"),
                                 httpx.RemoteProtocolError("tls")])
def test_no_answer_is_unreachable(exc):
    result = _probe("openrouter", _Hub(exc=exc), key=KEY)
    assert result["verdict"] == "unreachable" and result["status_code"] is None


def test_anything_else_is_an_error():
    result = _probe("openrouter", _Hub(exc=ValueError("odd")), key=KEY)
    assert result["verdict"] == "error"


def test_a_wrong_host_protocol_is_refused_before_sending():
    from agents.core.observability.egress_monitor import EGRESS_MONITOR

    hub = _Hub()
    result = _probe("openrouter", hub, key=KEY, environ={"OPENROUTER_BASE_URL": "https://api.anthropic.com/v1"})
    assert result["verdict"] == "refused" and hub.requests == []
    rows = [r for r in EGRESS_MONITOR.snapshot()["recent"]
            if r.get("plugin") == "llm:openrouter" and r.get("host") == "api.anthropic.com"]
    assert rows and rows[0]["allowed"] is False                  # recorded as refused, never sent


def test_the_read_is_in_the_egress_ledger(monkeypatch):
    from agents.core.observability import egress_monitor

    seen = []
    monkeypatch.setattr(egress_monitor.EGRESS_MONITOR, "record",
                        lambda plugin, host, method, **kw: seen.append((plugin, host, method, kw.get("allowed"))))
    _probe("anthropic", _Hub(), key=KEY)
    assert seen == [("llm:anthropic", "api.anthropic.com", "GET", True)]


def test_without_a_key_or_on_a_local_provider_nothing_is_sent():
    hub = _Hub()
    assert _probe("gemini", hub)["verdict"] == "not_configured"
    assert _probe("gemini", hub, key="   ")["verdict"] == "not_configured"
    assert _probe("ollama", hub, key=KEY)["verdict"] == "not_cloud"
    assert hub.requests == []
    with pytest.raises(KeyError):
        _probe("nope", hub, key=KEY)


def test_neither_the_key_nor_the_body_is_returned_or_logged(caplog):
    with caplog.at_level(logging.DEBUG, logger="jarvis.llm.provider_probe"):
        results = [_probe("anthropic", _Hub(), key=KEY), _probe("gemini", _Hub(status=401), key=KEY),
                   _probe("xai", _Hub(exc=ValueError(KEY)), key=KEY)]
    dumped = json.dumps(results) + " ".join(r.getMessage() for r in caplog.records)
    assert KEY not in dumped and BODY_SENTINEL not in dumped
    assert all(set(r) == {"provider", "display_name", "verdict", "working", "status_code", "models",
                          "checked_at", "cached", "throttled"} for r in results)


# ── the cache ────────────────────────────────────────────────────────────────────

def test_a_verdict_is_cached_per_provider_and_key():
    hub, clock = _Hub(), _Clock()
    first = _probe("anthropic", hub, key=KEY, clock=clock)
    clock.t += provider_probe.TTL_SECONDS - 1
    again = _probe("anthropic", hub, key=KEY, clock=clock)
    assert len(hub.requests) == 1 and again["cached"] is True and again["verdict"] == first["verdict"]
    _probe("anthropic", hub, key=KEY + "-rotated", clock=clock)            # a new key is probed afresh
    assert len(hub.requests) == 2
    clock.t += 1
    assert _probe("anthropic", hub, key=KEY, clock=clock)["cached"] is False   # expired
    assert len(hub.requests) == 3


def test_a_forced_recheck_is_throttled_then_allowed():
    hub, clock = _Hub(), _Clock()
    _probe("gemini", hub, key=KEY, clock=clock)
    clock.t += provider_probe.MIN_INTERVAL_SECONDS - 1
    throttled = _probe("gemini", hub, key=KEY, force=True, clock=clock)
    assert throttled["throttled"] is True and throttled["cached"] is True and len(hub.requests) == 1
    clock.t += 1
    forced = _probe("gemini", hub, key=KEY, force=True, clock=clock)
    assert forced["cached"] is False and len(hub.requests) == 2


def test_last_reads_the_cache_only(monkeypatch):
    clock = _Clock()
    assert provider_probe.last("anthropic", key=KEY, clock=clock) is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    _probe("anthropic", _Hub(status=401), clock=clock)
    cached = provider_probe.last("anthropic", clock=clock)
    assert cached["verdict"] == "auth_failed" and cached["cached"] is True
    clock.t += provider_probe.TTL_SECONDS
    assert provider_probe.last("anthropic", clock=clock) is None
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert provider_probe.last("anthropic", clock=clock) is None


def test_probe_all_asks_every_cloud_provider_with_a_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    hub = _Hub()
    results = asyncio.run(provider_probe.probe_all(client_factory=hub.factory))
    assert [r["provider"] for r in results] == [p.id for p in provider_probe.cloud_profiles()]
    assert "ollama" not in {r["provider"] for r in results}
    by = {r["provider"]: r["verdict"] for r in results}
    assert by["gemini"] == "ok" and by["anthropic"] == "not_configured"
    assert [str(r.url) for r in hub.requests] == [provider_probe.GEMINI_MODELS_URL]


# ── where it is used ─────────────────────────────────────────────────────────────

_TOKEN = "h380-token"


def test_the_admin_route(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    seen = []

    async def fake_probe(provider, *, force=False, **kw):
        seen.append((provider, force))
        return {"provider": provider, "verdict": "ok"}

    async def fake_all(*, force=False, **kw):
        seen.append(("*", force))
        return [{"provider": "anthropic", "verdict": "not_configured"}]

    monkeypatch.setattr(provider_probe, "probe", fake_probe)
    monkeypatch.setattr(provider_probe, "probe_all", fake_all)
    client = TestClient(web.app)
    path = "/api/admin/llm/providers/probe"
    assert client.post(path, json={}).status_code in (401, 403) and seen == []
    headers = {"X-Admin-Token": _TOKEN}
    assert client.post(path, json={}, headers=headers).json() == {
        "providers": [{"provider": "anthropic", "verdict": "not_configured"}]}
    assert client.post(path, json={"provider": " Gemini ", "force": True}, headers=headers).json() == {
        "providers": [{"provider": "gemini", "verdict": "ok"}]}
    client.post(path, json={"force": True}, headers=headers)
    assert seen == [("*", False), ("gemini", True), ("*", True)]

    async def unknown(provider, **kw):
        raise KeyError(provider)

    monkeypatch.setattr(provider_probe, "probe", unknown)
    assert client.post(path, json={"provider": "nope"}, headers=headers).status_code == 404


def test_the_command_center_asks_with_the_routes_own_key(monkeypatch):
    from agents.core.routers import onboarding

    seen = []

    async def fake_probe(provider, *, key=None, **kw):
        seen.append((provider, key))
        return {"provider": provider, "verdict": "auth_failed"}

    monkeypatch.setattr(provider_probe, "probe", fake_probe)
    router = SimpleNamespace(_anthropic_pool=SimpleNamespace(current_key=lambda: "pool-key"),
                             _gemini_pool=SimpleNamespace(current_key=lambda: None))
    assert asyncio.run(onboarding._cloud_probe(router, "claude"))["verdict"] == "auth_failed"
    asyncio.run(onboarding._cloud_probe(router, "gemini"))
    asyncio.run(onboarding._cloud_probe(router, "openrouter"))
    broken = SimpleNamespace(_anthropic_pool=SimpleNamespace(current_key=lambda: 1 / 0))
    asyncio.run(onboarding._cloud_probe(broken, "claude"))
    assert seen == [("anthropic", "pool-key"), ("gemini", None), ("openrouter", None), ("anthropic", None)]

    async def unknown(provider, **kw):
        raise KeyError(provider)

    monkeypatch.setattr(provider_probe, "probe", unknown)
    assert asyncio.run(onboarding._cloud_probe(router, "cloud-compatible")) is None
