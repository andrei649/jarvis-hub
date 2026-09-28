"""H273, the fourth review (review-H273e) — its findings, pinned.

- M1: the MCP transport asked a different question from the HTTP user guard, so with the
  env user token rotated away (and the managed one expired) or revoked, every route was
  locked but MCP answered a local caller with no token. One predicate now decides both.
- M2: the coordinator built its Orchestrator before loading the .env files, so its audit
  rows went unkeyed while the hub's were keyed, and the shared chain read as tampered.
- m1: JARVIS_HOST=::1 built an unbracketed URL that no loopback check recognised.
- m2: the CLI sent the admin token to any hub; it now sends it only to this machine.
- m4: the CLI's copy of the loopback rule agrees with the doctor's.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from agents.core.security import token_store as ts_mod
from agents.core.security.token_store import TokenStore

LOOPBACK = ("127.0.0.1", 50000)
_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def _mcp_on(web, monkeypatch):
    orig = web.orch.get_setting

    def fake(key, default=None):
        if key == "mcp.server_enabled":
            return True
        if key == "mcp.oauth_required":
            return False
        return orig(key, default)

    monkeypatch.setattr(web.orch, "get_setting", fake)


@pytest.fixture(autouse=True)
def real_guard():
    """The suite's conftest turns the user guard off for TestClient suites; these tests
    are about the guard, so they put the real one back."""
    from agents import web
    from agents.core.routers._deps import user_guard as routed

    web.app.dependency_overrides.pop(web._user_guard, None)
    web.app.dependency_overrides.pop(routed, None)
    yield


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = TokenStore(db_path=str(tmp_path / "tokens.db"))
    monkeypatch.setattr(ts_mod, "_store", s)
    return s


def _both(client, headers=None):
    """[an HTTP user route, the MCP transport] as one caller sees them."""
    return [client.get("/api/missions", headers=headers or {}).status_code,
            client.post("/api/mcp/server/rpc", json=_LIST, headers=headers or {}).status_code]


def test_a_rotated_and_expired_user_credential_locks_http_and_mcp_alike(monkeypatch, store):
    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "env-user-token")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "env-user-token")
    store.rotate("user", ttl_days=1 / 86400)             # supersedes the env token, lapses in 1 s
    time.sleep(1.2)
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert _both(client) == [401, 401]
        assert _both(client, {"x-user-token": "env-user-token"}) == [401, 401]


def test_revoking_every_user_credential_locks_http_and_mcp_alike(monkeypatch, store):
    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "env-user-token")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "env-user-token")
    store.revoke_all(revoke_env=True)
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert _both(client) == [401, 401]


def test_the_mcp_identity_check_refuses_a_revoked_credential_as_the_guard_does(monkeypatch, store):
    """The per-tool identity check on MCP's mutating tools asks the same predicate."""
    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "env-user-token")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "env-user-token")
    store.revoke_all(revoke_env=True)
    assert web._mcp_identity_check(None) is False
    assert web._mcp_identity_check("env-user-token") is False


def test_a_managed_token_alone_is_required_by_http_and_mcp_alike(monkeypatch, store):
    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    issued = store.issue("user", ttl_days=1)
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert _both(client) == [401, 401]
        assert _both(client, {"x-user-token": issued}) == [200, 200]


def test_a_hub_that_never_had_a_user_credential_keeps_the_localhost_posture(monkeypatch, store):
    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert _both(client) == [200, 200]


# ── M2: the coordinator loads the .env files before it builds ────────────────────

def test_the_coordinator_keys_the_audit_chain_from_the_env_file(tmp_path, monkeypatch):
    """The hub and the coordinator share one audit database: both must key it."""
    import asyncio
    import os

    from agents.core import env_provenance as ep

    saved = dict(os.environ)
    try:
        monkeypatch.setattr(ep, "REPO_ENV_FILE", tmp_path / "no-repo" / ".env", raising=False)
        home = tmp_path / "home"
        home.mkdir()
        (home / ".env").write_text("JARVIS_AUDIT_KEY=" + "k" * 40 + "\n", encoding="utf-8")
        monkeypatch.setenv("JARVIS_USER_HOME", str(home))
        monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("JARVIS_TESTING", "1")
        monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
        monkeypatch.setattr(ep, "_HUB_LOADED", None, raising=False)
        from scripts import coordinator

        async def build():
            orch = await coordinator._build_orchestrator()
            try:
                return orch.audit._key is not None
            finally:
                await orch.aclose()

        assert asyncio.run(build()) is True
    finally:
        os.environ.clear()
        os.environ.update(saved)


# ── m1: an IPv6 bind (JARVIS_HOST=::1) is a hub on this machine ──────────────────

@pytest.mark.parametrize("host", ["::1", "[::1]", " ::1 "])
def test_an_ipv6_bind_gives_a_bracketed_url_both_copies_call_this_machine(host):
    from agents.cli import client
    from scripts import doctor

    env = {"JARVIS_HOST": host, "JARVIS_PORT": "8080"}
    assert client.hub_url(env) == doctor.hub_url(env) == "http://[::1]:8080"
    assert client.is_loopback_url(client.hub_url(env)) is True
    assert doctor.is_loopback_url(doctor.hub_url(env)) is True


@pytest.mark.parametrize("module", ["agents.cli.client", "scripts.doctor"])
def test_hub_open_skips_the_proxy_for_an_ipv6_hub_on_this_machine(module, monkeypatch):
    import importlib
    import urllib.request

    mod = importlib.import_module(module)
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:3128")
    seen = []

    class _Opener:
        def open(self, request, timeout=None):
            return "opened"

    def build_opener(*handlers):
        seen.extend(handlers)
        return _Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    assert mod.hub_open(mod.hub_url({"JARVIS_HOST": "::1"}) + "/readyz") == "opened"
    proxies = [h for h in seen if isinstance(h, urllib.request.ProxyHandler)]
    assert proxies and all(p.proxies == {} for p in proxies)


def test_the_doctor_offers_the_admin_token_to_an_ipv6_hub_on_this_machine():
    from scripts import doctor

    env = {"JARVIS_HOST": "::1", "JARVIS_ADMIN_TOKEN": "adm"}
    assert doctor._hub_headers(env, doctor.hub_url(env)).get("x-admin-token") == "adm"


# ── m2: the CLI's admin token never crosses the network in clear text ────────────

def _cli_headers(url):
    from agents.cli.client import HubClient

    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def read(self):
            return b"{}"

    def opener(request, timeout):
        seen.update({k.lower(): v for k, v in request.header_items()})
        return _Resp()

    HubClient(url, admin_token="adm", user_token="usr", opener=opener).get("/api/status")
    return seen


@pytest.mark.parametrize("url, admin", [
    ("http://127.0.0.1:8080", True), ("http://[::1]:8080", True), ("http://::1:8080", True),
    ("http://localhost.:8080", True), ("https://hub.example.com", True),
    ("http://hub.lan:8080", False), ("http://10.0.0.5:8080", False), ("HTTP://[::2]:8080", False),
])
def test_the_cli_sends_the_admin_token_only_home_or_over_https(url, admin):
    headers = _cli_headers(url)
    assert headers["x-user-token"] == "usr"
    assert ("x-admin-token" in headers) is admin


# ── m4: the CLI's loopback rule and the doctor's are the same rule ───────────────

SPELLINGS = [
    ("http://127.0.0.1:8080", True), ("http://127.0.0.2:8080", True), ("http://127.1:8080", True),
    ("http://2130706433:8080", True), ("http://0x7f.1:8080", True), ("http://0177.0.0.1:8080", True),
    ("http://localhost.:8080", True), ("http://127.0.0.1.:8080", True), ("http://LOCALHOST:8080", True),
    ("http://[::1]:8080", True), ("http://[::ffff:127.0.0.1]:8080", True), ("http://[::ffff:7f00:1]:8080", True),
    ("http://::1:8080", True), ("http://user@::1:8080", True), ("http://::2:8080", False),
    ("http://hub.lan:8080", False), ("http://10.0.0.5:8080", False), ("http://[::2]:8080", False),
    ("http://localhost.evil.test:8080", False), ("http://128.0.0.1:8080", False),
    ("file:///tmp/x", False), ("data:text/plain,ok", False), ("http://:8080", False), ("http://[::1:8080", False),
]


@pytest.mark.parametrize("url, here", SPELLINGS)
def test_the_cli_and_the_doctor_agree_on_this_machine(url, here):
    from agents.cli import client
    from scripts import doctor

    assert client.is_loopback_url(url) is here
    assert doctor.is_loopback_url(url) is here


# ── n1: the REPL loads the .env files before its logging and imports ─────────────

_REPL_SPY = r"""
import os, sys
from pathlib import Path
import agents.core.env_provenance as ep
ep.REPO_ENV_FILE = Path(sys.argv[1])
import agents.run  # noqa: F401
print("LOG", os.path.exists(sys.argv[2]))
"""


@pytest.mark.timeout(240)
def test_the_repl_reads_its_log_file_from_the_env_file(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    log = tmp_path / "repl.log"
    env_file = tmp_path / "repo.env"
    env_file.write_text(f"JARVIS_LOG_FILE={log}\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("JARVIS_LOG_FILE",)}
    env.update({"JARVIS_TESTING": "1", "JARVIS_HOME": str(tmp_path / "data"),
                "JARVIS_USER_HOME": str(tmp_path / "user-home")})
    out = subprocess.run([sys.executable, "-c", _REPL_SPY, str(env_file), str(log)],
                         capture_output=True, text=True, timeout=200, env=env,
                         cwd=Path(__file__).resolve().parent.parent)
    assert "LOG True" in out.stdout, out.stderr[-2000:]


# ── n6: a refused root's note gives the real reason ──────────────────────────────

@pytest.mark.parametrize("key", ["JARVIS_HOME", "JARVIS_APP_ROOT", "JARVIS_MEMORY_DIR"])
def test_a_root_from_a_file_is_left_out_on_purpose_and_says_so(key):
    from agents.core import env_provenance as ep

    note = ep.note_for(key, ep.REPO_ENV)
    assert note == ep.PROCESS_ONLY_NOTE == ep.note_for(key, ep.USER_ENV)
    assert "before the .env files are loaded" not in note and "not in effect" in note
    assert ep.note_for(key, ep.PROCESS) == ""
