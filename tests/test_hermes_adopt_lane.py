"""Adopt lane: vendored Hermes web search providers run through Nerva's controls.

The providers (Exa, Brave Search free tier, Parallel) are upstream Hermes files under
``agents/vendor/hermes`` with only import rewrites. These tests drive them through a real
``PluginHTTPClient`` whose resolver and transport are faked (no network), so the manifest
allowlist, SSRF pinning, the egress ledger and the kernel hook are the real ones.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agents.core import http_client as hc
from agents.core.http_client import PluginHTTPClient
from agents.core.plugins import web_providers as wp
from agents.core.plugins import websearch as ws
from agents.core.resilience import CircuitBreaker
from agents.vendor.hermes_compat import httpx as compat_httpx
from agents.vendor.hermes_compat import os_env, plugin_ctx
from agents.vendor.hermes_compat.web_search_provider import get_provider_env

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "agents" / "vendor" / "hermes"
COMPAT = REPO / "agents" / "vendor" / "hermes_compat"

_spec = importlib.util.spec_from_file_location("hermes_vendor", REPO / "scripts" / "hermes_vendor.py")
hv = importlib.util.module_from_spec(_spec)
sys.modules["hermes_vendor"] = hv
_spec.loader.exec_module(hv)

KEYS = {"exa": "EXA_API_KEY", "brave-free": "BRAVE_SEARCH_API_KEY", "parallel": "PARALLEL_API_KEY"}
PUBLIC_IP = "93.184.216.34"


def _answer(request: httpx.Request) -> httpx.Response:
    host = request.headers.get("host", "")
    path = request.url.path
    if host == "api.exa.ai" and path == "/search":
        return httpx.Response(200, json={"results": [
            {"url": "https://a.example/1", "title": "Exa one", "highlights": ["h1", "h2"]},
            {"url": "https://a.example/2", "title": "Exa two", "highlights": []},
        ]})
    if host == "api.search.brave.com" and path == "/res/v1/web/search":
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Brave one", "url": "https://b.example/1", "description": "d1"},
            {"title": "Brave two", "url": "https://b.example/2", "description": "d2"},
            {"title": "Brave three", "url": "https://b.example/3", "description": "d3"},
        ]}})
    if host == "api.parallel.ai" and path == "/v1beta/search":
        return httpx.Response(200, json={"results": [
            {"url": "https://p.example/1", "title": "Par one", "excerpts": ["e1", "e2"]},
        ]})
    return httpx.Response(404, json={"error": "unexpected"})


class Egress:
    """A real PluginHTTPClient('websearch') with a fake resolver and transport."""

    def __init__(self, *, ip: str = PUBLIC_IP, status: int | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.resolved: list[str] = []
        self.ip = ip
        self.status = status

        def resolver(host, *, mode):
            self.resolved.append(host)
            return [self.ip], None

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.status is not None:
                return httpx.Response(self.status, text="nope")
            return _answer(request)

        self.client = PluginHTTPClient(
            "websearch", circuit_breaker=CircuitBreaker(key="test"),
            resolver=resolver, transport_factory=lambda _t: httpx.MockTransport(handler),
        )

    def body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content or b"{}")


@pytest.fixture
def egress():
    return Egress()


@pytest.fixture
def ledger(monkeypatch):
    rows: list[dict] = []

    def record(plugin, host, method, *, allowed, local, reason=""):
        rows.append({"plugin": plugin, "host": host, "method": method, "allowed": allowed,
                     "reason": reason})

    monkeypatch.setattr(hc, "_record_egress", record)
    return rows


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for env in (*KEYS.values(), "PARALLEL_SEARCH_MODE", "JARVIS_WEB_BACKEND",
                "JARVIS_WEB_PROVIDER_TIER", "JARVIS_WEB_RESCUE"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    hc.set_egress_kernel_hook(None)
    yield
    hc.set_egress_kernel_hook(None)


VIEW = SimpleNamespace(tavily_api_key="", searxng_url="")


# ── registration ─────────────────────────────────────────────────────────────

def test_the_adopted_providers_register_after_the_builtins_on_websearch_egress():
    assert wp.ADOPTED_PROVIDERS == ("exa", "brave-free", "parallel")
    names = wp.search_providers()
    assert names[:3] == ("tavily", "searxng", "duckduckgo")
    tiers = {"exa": "paid", "brave-free": "free", "parallel": "paid"}
    for name, tier in tiers.items():
        provider = wp.get_search_provider(name)
        assert isinstance(provider, wp.SearchProvider)
        assert provider.plugin_id == "websearch"
        assert provider.tier == tier
        assert provider.keyless is False
    assert wp.auto_order()[-1].name == "duckduckgo"


def test_each_adopted_provider_is_off_until_its_key_is_set(monkeypatch):
    for name, env in KEYS.items():
        provider = wp.get_search_provider(name)
        assert provider.configured(VIEW) is False
        monkeypatch.setenv(env, "  ")
        assert provider.configured(VIEW) is False
        monkeypatch.setenv(env, "k-123")
        assert provider.configured(VIEW) is True
        monkeypatch.delenv(env)
    assert wp.resolve(VIEW, backend="exa").reason == wp.REASON_NOT_CONFIGURED


def test_the_hosts_are_on_the_websearch_manifest_allowlist(monkeypatch):
    client = PluginHTTPClient.for_plugin("websearch")
    for host in ("api.exa.ai", "api.search.brave.com", "api.parallel.ai"):
        client._enforce_egress(f"https://{host}/x")  # strict: must not raise


def test_a_provider_without_a_reviewed_tier_is_refused():
    from agents.vendor.hermes_compat.web_search_provider import WebSearchProvider

    class Rogue(WebSearchProvider):
        name = "rogue"

        def is_available(self):
            return True

    ctx = plugin_ctx.PluginContext(wp, "rogue")
    with pytest.raises(ValueError, match="tier"):
        ctx.register_web_search_provider(Rogue())
    with pytest.raises(TypeError):
        ctx.register_web_search_provider(object())
    assert "rogue" not in wp.search_providers()
    assert not hasattr(ctx, "register_tool")


# ── searching through the egress client ──────────────────────────────────────

async def test_exa_searches_through_the_egress_client_and_maps_rows(monkeypatch, egress, ledger):
    monkeypatch.setenv("EXA_API_KEY", "exa-secret")
    rows = await wp.get_search_provider("exa").search(egress.client, VIEW, "solar news", 5)
    assert rows == [
        {"title": "Exa one", "url": "https://a.example/1", "snippet": "h1 h2"},
        {"title": "Exa two", "url": "https://a.example/2", "snippet": ""},
    ]
    request = egress.requests[0]
    assert request.method == "POST" and request.url.host == PUBLIC_IP  # pinned dial
    assert request.headers["host"] == "api.exa.ai"
    assert request.headers["x-api-key"] == "exa-secret"
    assert request.headers["x-exa-integration"] == "hermes-agent"
    assert egress.body() == {"query": "solar news", "numResults": 5,
                             "contents": {"highlights": True}}
    assert ledger == [{"plugin": "websearch", "host": "api.exa.ai", "method": "POST",
                       "allowed": True, "reason": ""}]


async def test_brave_free_searches_through_the_egress_client_and_maps_rows(monkeypatch, egress, ledger):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-secret")
    rows = await wp.get_search_provider("brave-free").search(egress.client, VIEW, "q", 2)
    assert rows == [{"title": "Brave one", "url": "https://b.example/1", "snippet": "d1"},
                    {"title": "Brave two", "url": "https://b.example/2", "snippet": "d2"}]
    request = egress.requests[0]
    assert request.method == "GET" and request.headers["host"] == "api.search.brave.com"
    assert request.headers["x-subscription-token"] == "brave-secret"
    assert request.url.params["q"] == "q" and request.url.params["count"] == "2"
    assert [r["host"] for r in ledger] == ["api.search.brave.com"]


async def test_parallel_searches_through_the_egress_client_and_maps_rows(monkeypatch, egress):
    monkeypatch.setenv("PARALLEL_API_KEY", "par-secret")
    rows = await wp.get_search_provider("parallel").search(egress.client, VIEW, "q", 3)
    assert rows == [{"title": "Par one", "url": "https://p.example/1", "snippet": "e1 e2"}]
    request = egress.requests[0]
    assert request.headers["host"] == "api.parallel.ai"
    assert request.headers["x-api-key"] == "par-secret"
    assert request.headers["parallel-beta"] == "search-extract-2025-10-10"
    assert egress.body() == {"objective": "q", "search_queries": ["q"], "mode": "agentic",
                             "max_results": 3}
    monkeypatch.setenv("PARALLEL_SEARCH_MODE", "fast")
    await wp.get_search_provider("parallel").search(egress.client, VIEW, "q", 3)
    assert egress.body()["mode"] == "fast"


async def test_web_search_plugin_selects_an_adopted_backend_and_taints_rows(monkeypatch, egress):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    monkeypatch.setenv("JARVIS_WEB_BACKEND", "brave-free")
    plugin = ws.WebSearchPlugin()
    plugin._client = egress.client
    outcome = await plugin.search_detailed("q", 3)
    assert outcome.provider == "brave-free" and outcome.reason == ""
    assert [r["url"] for r in outcome.rows] == [f"https://b.example/{i}" for i in (1, 2, 3)]
    from agents.core.security import taint
    assert all(taint.is_tainted(r) for r in outcome.rows)


# ── refusals by Nerva's egress layer ─────────────────────────────────────────

async def test_a_private_address_is_refused_by_the_ssrf_guard(monkeypatch, ledger):
    egress = Egress(ip="10.0.0.7")  # api.exa.ai "resolving" into the LAN
    monkeypatch.setenv("EXA_API_KEY", "k")
    with pytest.raises(wp.PolicyBlock):
        await wp.get_search_provider("exa").search(egress.client, VIEW, "q", 5)
    assert egress.requests == []
    assert ledger and ledger[0]["allowed"] is False


async def test_an_unlisted_host_is_refused_by_the_manifest_allowlist(monkeypatch, egress, ledger):
    from agents.vendor.hermes.plugins.web.brave_free import provider as brave

    monkeypatch.setattr(brave, "_BRAVE_ENDPOINT", "https://evil.example/collect")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    with pytest.raises(wp.PolicyBlock):
        await wp.get_search_provider("brave-free").search(egress.client, VIEW, "q", 5)
    assert egress.requests == [] and egress.resolved == []
    assert ledger[0]["host"] == "evil.example" and ledger[0]["allowed"] is False


async def test_the_kernel_hook_can_deny_an_adopted_search(monkeypatch, egress):
    seen = []

    def deny(plugin, method, url, host):
        seen.append((plugin, method, host))
        return "estop engaged"

    hc.set_egress_kernel_hook(deny)
    monkeypatch.setenv("PARALLEL_API_KEY", "k")
    with pytest.raises(wp.PolicyBlock):
        await wp.get_search_provider("parallel").search(egress.client, VIEW, "q", 5)
    assert seen == [("websearch", "POST", "api.parallel.ai")]
    assert egress.requests == []


async def test_a_policy_block_through_websearch_is_not_rescued(monkeypatch):
    egress = Egress(ip="192.168.1.20")
    monkeypatch.setenv("EXA_API_KEY", "k")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    plugin = ws.WebSearchPlugin()
    plugin._client = egress.client
    outcome = await plugin.search_detailed("q")
    assert outcome.provider == "exa" and outcome.reason == "policy_blocked"
    assert outcome.rescued_from == "" or outcome.rescued_from is None
    assert egress.requests == []


async def test_an_http_error_is_a_provider_failure_and_never_logs_the_key(monkeypatch, caplog):
    egress = Egress(status=401)
    monkeypatch.setenv("EXA_API_KEY", "exa-very-secret")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-very-secret")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(wp.ProviderFailure, match="http_401"):
        await wp.get_search_provider("exa").search(egress.client, VIEW, "private query", 5)
    with pytest.raises(wp.ProviderFailure, match="http_401"):
        await wp.get_search_provider("brave-free").search(egress.client, VIEW, "private query", 5)
    assert "very-secret" not in caplog.text
    assert "private query" not in caplog.text


# ── the compat httpx ─────────────────────────────────────────────────────────

def test_the_compat_httpx_refuses_without_a_bound_egress_client():
    with pytest.raises(compat_httpx.EgressRefused):
        compat_httpx.get("https://api.exa.ai/")
    with pytest.raises(compat_httpx.EgressRefused):
        compat_httpx.Client().post("https://api.exa.ai/")


async def test_a_refusal_is_sticky_for_the_rest_of_the_call():
    calls = []

    class Refusing:
        async def get(self, url, **kw):
            calls.append(url)
            raise hc.PluginEgressError("egress blocked: nope")

    loop = asyncio.get_running_loop()

    def vendored():
        for _ in range(2):
            with contextlib.suppress(compat_httpx.RequestError):
                compat_httpx.get("https://api.exa.ai/")

    with compat_httpx.bound_egress(Refusing(), loop) as call:
        await asyncio.to_thread(vendored)
    assert len(calls) == 1 and call.policy_block == "egress_blocked"


async def test_a_dns_failure_is_a_failure_not_a_block():
    class Unresolved:
        async def get(self, url, **kw):
            raise hc.PluginEgressError("egress blocked: DNS resolution failed for x")

    with compat_httpx.bound_egress(Unresolved(), asyncio.get_running_loop()) as call, \
            pytest.raises(compat_httpx.ConnectError):
        await asyncio.to_thread(compat_httpx.get, "https://api.exa.ai/")
    assert call.policy_block == "" and call.failure == "dns_failed"


async def test_vendored_code_on_the_event_loop_is_refused_not_deadlocked():
    class Never:
        async def get(self, url, **kw):  # pragma: no cover - must not be reached
            raise AssertionError("dialled")

    with compat_httpx.bound_egress(Never(), asyncio.get_running_loop()), \
            pytest.raises(compat_httpx.ConnectError):
        compat_httpx.get("https://api.exa.ai/")


# ── secrets ──────────────────────────────────────────────────────────────────

def test_env_reads_are_limited_to_the_adopted_names(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-other")
    monkeypatch.setenv("EXA_API_KEY", " exa ")
    assert get_provider_env("OPENAI_API_KEY") == ""
    assert get_provider_env("EXA_API_KEY") == "exa"
    assert os_env.getenv("OPENAI_API_KEY") is None
    assert os_env.getenv("HOME", "d") == "d"
    assert not hasattr(os_env, "environ") and not hasattr(os_env, "system")


def test_vendored_modules_see_the_compat_os_and_httpx():
    from agents.vendor.hermes.plugins.web import _common
    from agents.vendor.hermes.plugins.web.parallel import provider as par

    assert _common.httpx is compat_httpx
    assert par.os is os_env


# ── structure: no bare client in vendored code ───────────────────────────────

_NETWORK = {"httpx", "httpcore", "requests", "aiohttp", "urllib3", "socket", "ssl", "http",
            "urllib", "websocket", "websockets", "exa_py", "parallel", "subprocess"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"__import__", "exec", "eval"}:
            names.append(node.func.id)
    return names


def test_no_vendored_or_compat_module_imports_a_network_library():
    offenders = []
    for root in (VENDOR, COMPAT):
        for path in sorted(root.rglob("*.py")):
            for name in _imports(path):
                if name.split(".")[0] in _NETWORK or name in {"__import__", "exec", "eval"}:
                    offenders.append(f"{path.relative_to(REPO)}: {name}")
    assert offenders == []


def test_every_vendored_python_file_is_fully_mapped_onto_the_compat_layer():
    for path in sorted(VENDOR.rglob("*.py")):
        rel = path.relative_to(VENDOR).as_posix()
        assert hv.unmapped_imports(path.read_text(encoding="utf-8"), rel) == [], rel


# ── manifest and the sync script ─────────────────────────────────────────────

def test_the_manifest_matches_the_vendored_bytes():
    manifest = json.loads((VENDOR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["upstream"]["commit"] == "9c0560f8e6856bc14c11bfe6d666df06be14d2de"
    assert manifest["upstream"]["license"] == "MIT"
    assert manifest["rewrite_rules"] == hv.rules_record()
    for entry in manifest["files"]:
        data = (VENDOR / entry["path"]).read_bytes()
        assert hv.sha256(data) == entry["vendored_sha256"], entry["path"]
        if not entry["rules_applied"]:
            assert entry["upstream_sha256"] == entry["vendored_sha256"], entry["path"]
    assert (VENDOR / "MANIFEST.json").read_text(encoding="utf-8") == hv.dump_manifest(manifest)
    assert "MIT License" in (VENDOR / "LICENSE").read_text(encoding="utf-8")
    assert manifest["upstream"]["commit"] in (VENDOR / "NOTICE.md").read_text(encoding="utf-8")


def test_status_is_clean_for_the_tree():
    out = _Out()
    assert hv.main(["status"], out=out) == 0, out.text


def test_the_rewrite_is_idempotent():
    for path in sorted(VENDOR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert hv.rewrite(text)[0] == text, path
    sample = ("import httpx\nimport os\nfrom agent.web_search_provider import X\n"
              "    from plugins.web.keyless_mcp import y\nfrom plugins.web._common import z\n"
              "    from tools.interrupt import i\n    import tools.web_tools as _wt\n"
              "    import pm\n        from exa_py import Exa  # lazy\n"
              "        import parallel  # lazy\n")
    once, applied = hv.rewrite(sample)
    assert len(applied) == len(hv.REWRITE_RULES)
    assert hv.rewrite(once) == (once, [])
    assert once.count("\n") == sample.count("\n")
    assert hv.unmapped_imports(once) == []
    assert "        from agents.vendor.hermes_compat.sdk import parallel  # lazy\n" in once


class _Out:
    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)

    def writelines(self, lines):
        self.parts.extend(lines)

    @property
    def text(self):
        return "".join(self.parts)


UPSTREAM_TEXT = "import httpx\n\n\ndef ping():\n    return httpx.get('https://api.exa.ai/')\n"


@pytest.fixture
def sandbox(tmp_path):
    upstream = tmp_path / "upstream"
    (upstream / "plugins" / "web").mkdir(parents=True)
    (upstream / "plugins" / "web" / "x.py").write_text(UPSTREAM_TEXT, encoding="utf-8")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    return upstream, vendor


def _run(argv, vendor):
    out = _Out()
    return hv.main(argv, vendor_root=vendor, out=out), out.text


def test_pull_then_diff_and_status_track_an_upstream_change(sandbox):
    upstream, vendor = sandbox
    code, text = _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40,
                       "plugins/web/x.py"], vendor)
    assert code == 0, text
    vendored = (vendor / "plugins/web/x.py").read_text(encoding="utf-8")
    assert vendored.startswith("from agents.vendor.hermes_compat import httpx\n")
    manifest_once = (vendor / "MANIFEST.json").read_bytes()
    assert _run(["status", "--upstream", str(upstream)], vendor)[0] == 0
    assert _run(["diff", "--upstream", str(upstream)], vendor)[0] == 0

    # Deterministic: pulling the same text again changes nothing.
    assert _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40,
                 "plugins/web/x.py"], vendor)[0] == 0
    assert (vendor / "MANIFEST.json").read_bytes() == manifest_once

    # Upstream moves on: diff shows the change, rewritten; status says BEHIND.
    (upstream / "plugins/web/x.py").write_text(
        UPSTREAM_TEXT.replace("api.exa.ai/", "api.exa.ai/v2"), encoding="utf-8")
    code, text = _run(["diff", "--upstream", str(upstream)], vendor)
    assert code == 1
    assert "+    return httpx.get('https://api.exa.ai/v2')" in text
    assert "-    return httpx.get('https://api.exa.ai/')" in text
    assert "import httpx\n" not in text.replace("from agents.vendor.hermes_compat import httpx", "")
    code, text = _run(["status", "--upstream", str(upstream)], vendor)
    assert code == 1 and "BEHIND" in text

    # Pull it: the manifest follows and diff is clean again.
    assert _run(["pull", "--upstream", str(upstream), "--commit", "b" * 40,
                 "plugins/web/x.py"], vendor)[0] == 0
    entry = json.loads((vendor / "MANIFEST.json").read_text())["files"][0]
    assert entry["upstream_commit"] == "b" * 40
    assert _run(["diff", "--upstream", str(upstream)], vendor)[0] == 0


def test_status_detects_a_local_edit_and_pull_refuses_to_overwrite_it(sandbox):
    upstream, vendor = sandbox
    _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40, "plugins/web/x.py"], vendor)
    target = vendor / "plugins/web/x.py"
    target.write_text(target.read_text() + "# local tweak\n", encoding="utf-8")
    code, text = _run(["status"], vendor)
    assert code == 1 and "EDITED" in text
    code, text = _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40,
                       "plugins/web/x.py"], vendor)
    assert code == 2 and "local edits" in text
    assert _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40, "--force",
                 "plugins/web/x.py"], vendor)[0] == 0
    (vendor / "plugins/web/stray.py").write_text("x = 1\n", encoding="utf-8")
    code, text = _run(["status"], vendor)
    assert code == 1 and "EXTRA   plugins/web/stray.py" in text


def test_pull_refuses_a_file_the_compat_layer_does_not_cover(sandbox):
    upstream, vendor = sandbox
    (upstream / "plugins/web/bad.py").write_text(
        "import requests\nfrom hermes_cli.config import load_config\n", encoding="utf-8")
    code, text = _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40,
                       "plugins/web/bad.py"], vendor)
    assert code == 2 and "requests" in text and "hermes_cli.config" in text
    assert not (vendor / "plugins/web/bad.py").exists()
    code, text = _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40,
                       "../outside.py"], vendor)
    assert code == 2
