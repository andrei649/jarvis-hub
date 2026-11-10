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
from agents.vendor.hermes_compat.web_search_provider import get_provider_env, provider_scope

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
    # Brave counts as paid: Nerva cannot tell a free-tier key from a paid-plan one.
    tiers = {"exa": "paid", "brave-free": "paid", "parallel": "paid"}
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
    assert request.headers["x-exa-integration"] == "nerva"  # rewrite rule, not a hand edit
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
    monkeypatch.setenv("PARALLEL_SEARCH_MODE", "fast")
    with provider_scope("exa"):
        assert get_provider_env("OPENAI_API_KEY") == ""
        assert get_provider_env("EXA_API_KEY") == "exa"
        assert os_env.getenv("OPENAI_API_KEY") is None
        assert os_env.getenv("PARALLEL_SEARCH_MODE") is None  # parallel's setting, not exa's
        assert os_env.getenv("HOME", "d") == "d"
    with provider_scope("parallel"):
        assert os_env.getenv("PARALLEL_SEARCH_MODE") == "fast"
    assert not hasattr(os_env, "environ") and not hasattr(os_env, "system")


def test_one_provider_cannot_read_another_providers_key(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa-key")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
    with provider_scope("brave-free"):
        assert get_provider_env("EXA_API_KEY") == ""
        assert get_provider_env("BRAVE_SEARCH_API_KEY") == "brave-key"
    assert get_provider_env("EXA_API_KEY") == ""  # outside any provider scope: nothing
    from agents.vendor.hermes.plugins.web.exa.provider import ExaWebSearchProvider
    assert ExaWebSearchProvider().is_available() is False  # unscoped
    assert wp.get_search_provider("exa").configured(VIEW) is True  # the adapter scopes it


def test_the_new_key_names_are_managed_and_reported():
    from agents.core import code_env, support_bundle

    for name in KEYS.values():
        assert name in code_env._MANAGED_NAMES
        assert name in support_bundle._OTHER_KEYS["tools"]


def test_vendored_modules_see_the_compat_os_and_httpx():
    from agents.vendor.hermes.plugins.web import _common
    from agents.vendor.hermes.plugins.web.parallel import provider as par

    assert _common.httpx is compat_httpx
    assert par.os is os_env


# ── structure: the vendored tree stays inside an allowlist ───────────────────

def test_every_vendored_file_is_inside_the_allowlist():
    """The same allowlist pull and status apply (scripts/hermes_vendor.py), run on every CI
    pass: safe stdlib modules, the compat layer and vendored siblings only; data-only
    non-Python files; no symlinks."""
    offenders = []
    for path in sorted(VENDOR.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(VENDOR).as_posix()
        if path.is_symlink():
            offenders.append(f"{rel}: symlink")
            continue
        if not path.is_file() or rel in {"LICENSE"}:
            continue
        offenders += [f"{rel}: {p}" for p in hv.content_problems(path.read_bytes(), rel)]
    assert offenders == []


#: What the (Nerva-written) compat layer may import: no network or process library.
_COMPAT_ALLOWED = hv.SAFE_STDLIB | {"threading", "contextvars", "concurrent.futures", "importlib",
                                    "importlib.util", "pathlib", "sys", "agents.core.env_config"}


def test_no_compat_module_imports_a_network_library():
    offenders = []
    for path in sorted(COMPAT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "."] if node.level == 0 else ["<relative>"]
            for name in names:
                if name not in _COMPAT_ALLOWED and not name.startswith("agents.vendor."):
                    offenders.append(f"{path.relative_to(REPO)}: {name}")
    assert offenders == []


ESCAPES = {
    "urllib.request": "import urllib.request\ndef f(u):\n    return urllib.request.urlopen(u).read()\n",
    "subprocess": "import subprocess\ndef f(u):\n    return subprocess.run(['curl', u])\n",
    "socket": "import socket\ndef f():\n    return socket.create_connection(('x', 80))\n",
    "from os import environ": "from os import environ\ndef f():\n    return environ['TAVILY_API_KEY']\n",
    "import os, re": "import os, re\ndef f():\n    return os.environ['TAVILY_API_KEY']\n",
    "import os as _os": "import os as _os\ndef f():\n    return _os.environ\n",
    "os_env aliased": "from agents.vendor.hermes_compat import os_env as env\n",
    "importlib": "import importlib\ndef f(u):\n    return importlib.import_module('httpx').get(u)\n",
    "asyncio.open_connection": "import asyncio\nasync def f():\n    return await asyncio.open_connection('x', 80)\n",
    "from asyncio import": "from asyncio import open_connection\n",
    "getattr string": "import asyncio\ndef f():\n    return getattr(asyncio, 'open_connection')\n",
    "builtins": "import builtins\ndef f(u):\n    return builtins.__import__('httpx').get(u)\n",
    "__import__": "def f():\n    return __import__('httpx')\n",
    "sys.modules": "import sys\ndef f(u):\n    return sys.modules['httpx'].get(u)\n",
    "relative out of the tree": "from ....core.http_client import PluginHTTPClient\n",
    "imaplib": "import imaplib\n",
    "xmlrpc": "import xmlrpc.client\n",
    "multiprocessing.connection": "from multiprocessing.connection import Client\n",
    "ctypes": "import ctypes\n",
    "webbrowser": "import webbrowser\n",
    "http.client": "import http.client\n",
    "open": "def f():\n    return open('/etc/passwd').read()\n",
    "plugin_ctx": "from agents.vendor.hermes_compat import plugin_ctx\n",
    "agents.core": "from agents.core.http_client import PluginHTTPClient\n",
}


@pytest.mark.parametrize("name", sorted(ESCAPES))
def test_the_allowlist_refuses_every_escape(name):
    text, _ = hv.rewrite(ESCAPES[name])
    assert hv.unmapped_imports(text, "plugins/web/x/provider.py"), name


def test_the_allowlist_accepts_only_relative_imports_inside_the_package():
    assert hv.unmapped_imports("from ._common import x\n", "plugins/web/x/provider.py") == []
    assert hv.unmapped_imports("from .. import web\n", "plugins/web/x/provider.py")


@pytest.mark.parametrize(("rel", "data"), [
    ("plugins/web/x/hook.pth", b"import os\n"),
    ("plugins/web/x/run.sh", b"curl evil\n"),
    ("plugins/web/x/plugin.yaml", b"a: !!python/object/apply:os.system ['id']\n"),
    ("plugins/web/x/blob.json", b"{not json"),
    ("plugins/web/x/bin.txt", b"\0\1"),
])
def test_non_python_files_must_be_plain_data(rel, data):
    assert hv.content_problems(data, rel)
    assert hv.content_problems(b"name: web-x\nkind: backend\n", "plugins/web/x/plugin.yaml") == []


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
              "        import parallel  # lazy\n"
              '        client.headers["x-exa-integration"] = "hermes-agent"\n'
              "from providers.base import ProviderProfile\nfrom providers import register_provider\n"
              "from agent.reasoning_effort import clamp_effort\nfrom agent import reasoning_effort as re_\n"
              "    from agent.account_usage import AccountUsageSnapshot\n"
              "        from hermes_cli.version_info import hermes_user_agent\n"
              "import threading\n        import urllib.request\n")
    once, applied = hv.rewrite(sample)
    assert len(applied) == len(hv.REWRITE_RULES)
    assert hv.rewrite(once) == (once, [])
    assert once.count("\n") == sample.count("\n")
    assert hv.unmapped_imports("\n".join(line.strip() for line in once.splitlines())) == []
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


def test_pull_refuses_a_symlink_out_of_the_clone(sandbox, tmp_path):
    upstream, vendor = sandbox
    secret = tmp_path / "secret.env"
    secret.write_text("TOP_SECRET=1\n", encoding="utf-8")
    (upstream / "plugins/web/plugin.yaml").symlink_to(secret)
    code, text = _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40,
                       "plugins/web/plugin.yaml"], vendor)
    assert code == 2 and "regular file" in text
    assert not (vendor / "plugins/web/plugin.yaml").exists()
    outside = tmp_path / "elsewhere"
    (outside / "web").mkdir(parents=True)
    (outside / "web" / "y.py").write_text("x = 1\n", encoding="utf-8")
    (upstream / "linked").symlink_to(outside, target_is_directory=True)
    code, _ = _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40,
                    "linked/web/y.py"], vendor)
    assert code == 2


def test_status_checks_rules_applied_against_the_bytes(sandbox):
    upstream, vendor = sandbox
    _run(["pull", "--upstream", str(upstream), "--commit", "a" * 40, "plugins/web/x.py"], vendor)
    manifest = json.loads((vendor / "MANIFEST.json").read_text())
    manifest["files"][0]["rules_applied"] = []
    (vendor / "MANIFEST.json").write_text(hv.dump_manifest(manifest), encoding="utf-8")
    code, text = _run(["status"], vendor)
    assert code == 1 and "rules_applied" in text
    manifest["files"][0]["rules_applied"] = ["httpx", "exa-sdk"]
    (vendor / "MANIFEST.json").write_text(hv.dump_manifest(manifest), encoding="utf-8")
    code, text = _run(["status", "--upstream", str(upstream)], vendor)
    assert code == 1 and "DRIFT" in text


# ── review fixes: executor, deadlines, logs, redirects ────────────────────────

class Slow:
    """An egress client whose requests never answer; records their cancellation."""

    def __init__(self):
        self.started = 0
        self.cancelled = asyncio.Event()

    async def _wait(self, url, **kw):
        self.started += 1
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    get = post = _wait


async def test_many_concurrent_searches_do_not_starve_the_default_executor(monkeypatch):
    """Vendored code runs on its own executor: the egress client's DNS resolution
    (asyncio.to_thread) must still find a default worker free, even with a tiny pool."""
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_running_loop()
    tiny = ThreadPoolExecutor(max_workers=2)
    loop.set_default_executor(tiny)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    brave = wp.get_search_provider("brave-free")

    async def one():
        return await brave.search(Egress().client, VIEW, "q", 3)

    async def bystander():
        return await asyncio.to_thread(lambda: "free")

    results = await asyncio.wait_for(asyncio.gather(*[one() for _ in range(12)], bystander()),
                                     timeout=10)
    assert results[-1] == "free" and all(len(r) == 3 for r in results[:-1])


async def test_a_cancelled_caller_releases_the_worker_and_the_request(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "k")
    slow = Slow()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(wp.get_search_provider("exa").search(slow, VIEW, "q", 3), 0.3)
    await asyncio.wait_for(slow.cancelled.wait(), timeout=2)  # the worker gave up promptly
    assert slow.started == 1


async def test_a_search_past_its_deadline_fails_and_stops_waiting(monkeypatch):
    monkeypatch.setenv("PARALLEL_API_KEY", "k")
    monkeypatch.setattr(plugin_ctx, "SEARCH_DEADLINE_SECONDS", 0.3)
    slow = Slow()
    with pytest.raises(wp.ProviderFailure, match="timeout"):
        await wp.get_search_provider("parallel").search(slow, VIEW, "q", 3)
    await asyncio.wait_for(slow.cancelled.wait(), timeout=2)


async def test_a_later_dictconfig_cannot_make_vendored_code_log_a_query(monkeypatch, egress):
    import io
    import logging.config

    buf = io.StringIO()
    logging.config.dictConfig({
        "version": 1, "disable_existing_loggers": False,
        "handlers": {"s": {"class": "logging.StreamHandler", "stream": buf}},
        "loggers": {"agents.vendor": {"level": "DEBUG", "handlers": ["s"]}}})
    try:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
        await wp.get_search_provider("brave-free").search(
            egress.client, VIEW, "my private medical question", 3)
    finally:
        vendor_logger = logging.getLogger("agents.vendor")
        for handler in list(vendor_logger.handlers):
            vendor_logger.removeHandler(handler)
        vendor_logger.setLevel(logging.NOTSET)
    assert "private medical" not in buf.getvalue()


async def test_a_credential_request_never_follows_redirects():
    class Never:
        async def get(self, url, **kw):  # pragma: no cover - must not be reached
            raise AssertionError("dialled")

    with compat_httpx.bound_egress(Never(), asyncio.get_running_loop()) as call, \
            pytest.raises(compat_httpx.ConnectError):
        await asyncio.to_thread(compat_httpx.get, "https://api.exa.ai/",
                                headers={"X-API-Key": "k"}, follow_redirects=True)
    assert call.requests == 0 and call.failure == "redirect_with_credentials"


def test_nerva_package_markers_hold_only_a_docstring():
    for rel in hv._LOCAL_PACKAGE_MARKERS:
        assert hv._docstring_only((VENDOR / rel).read_bytes()), rel
    assert not hv._docstring_only(b'"""doc"""\nimport httpx\n')
    assert not hv._docstring_only(b'"""doc"""\nfrom agents.core import http_client\n')
