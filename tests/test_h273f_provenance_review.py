"""H273, the fifth review (review-H273f) — its findings, pinned.

- MAJOR-1: the admin guard still trusted a loopback caller once no admin credential was
  *active* (every one revoked, or rotated and expired), so a local process with no token
  minted a fresh user token and reopened every user route and MCP. Like the user tier,
  the admin tier now asks whether a credential was ever configured.
- m1: a managed user token that expired counted as never configured. An expired row
  stays in the store, and it counts now.
- m2: the CLI withheld the admin token from a plain-http hub on another machine and then
  told the owner to set the token they had set. It now says it withheld it.
- m3: with JARVIS_RUNTIME_LOG only in a .env file, the supervisor wrote its respawn
  events to the default file, apart from the coordinator's cycles.
- m4: the four survivors: an admin-only CLI environment, the loopback spellings for the
  admin token, the coordinator's run() load and the reality-evidence harness's.
- n1: a bare IPv6 hub whose first group is not empty is read the way http.client dials it.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from agents.core.security import token_store as ts_mod
from agents.core.security.token_store import TokenStore
from tests.test_h273e_provenance_review import SPELLINGS, _both, _mcp_on, real_guard  # noqa: F401

LOOPBACK = ("127.0.0.1", 50000)
REMOTE = ("192.0.2.7", 50000)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = TokenStore(db_path=str(tmp_path / "tokens.db"))
    monkeypatch.setattr(ts_mod, "_store", s)
    return s


def _tokens(web, monkeypatch, *, user="", admin=""):
    monkeypatch.setattr(web, "USER_TOKEN", user)
    monkeypatch.setattr(web, "ADMIN_TOKEN", admin)
    for name, value in (("JARVIS_USER_TOKEN", user), ("JARVIS_ADMIN_TOKEN", admin)):
        if value:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)


def _mint(client):
    return client.post("/api/admin/rotate-tokens", json={"scope": "user"})


# ── MAJOR-1: the admin tier asks "was one ever configured", as the user tier does ──

@pytest.mark.parametrize("posture", ["user_env_revoke_all", "both_env_revoke_all", "admin_rotated_expired"])
def test_after_every_credential_is_gone_no_local_caller_mints_a_token(posture, monkeypatch, store):
    from agents import web

    if posture == "user_env_revoke_all":
        _tokens(web, monkeypatch, user="env-user")
        store.revoke_all(revoke_env=True)
    elif posture == "both_env_revoke_all":
        _tokens(web, monkeypatch, user="env-user", admin="env-admin")
        store.revoke_all(revoke_env=True)
    else:
        _tokens(web, monkeypatch, user="env-user", admin="env-admin")
        store.rotate("admin", ttl_days=1 / 86400)
        store.revoke_all("user", revoke_env=True)
        time.sleep(1.2)
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert _both(client) == [401, 401]
        assert _mint(client).status_code == 401
        assert client.get("/api/admin/mcp").status_code == 401
        assert _both(client) == [401, 401]


def test_a_box_that_never_had_an_admin_credential_still_mints_its_first_from_loopback(monkeypatch, store):
    from agents import web

    _tokens(web, monkeypatch)
    with TestClient(web.app, client=LOOPBACK) as client:
        minted = _mint(client)
        assert minted.status_code == 200
    with TestClient(web.app, client=REMOTE) as client:
        assert _mint(client).status_code == 403


def test_an_admin_env_token_alone_closes_the_loopback_fallback(monkeypatch, store):
    from agents import web

    _tokens(web, monkeypatch, admin="env-admin")             # set, never rotated: no store flag
    with TestClient(web.app, client=LOOPBACK) as client:
        assert client.get("/api/admin/mcp").status_code == 401
        assert client.get("/api/admin/mcp", headers={"x-admin-token": "env-admin"}).status_code == 200


def test_the_owner_flag_on_chat_follows_the_admin_guard(monkeypatch, store):
    from starlette.requests import Request

    from agents import web

    def principal():
        scope = {"type": "http", "headers": [], "client": LOOPBACK, "method": "POST", "path": "/chat"}
        return web._web_principal(Request(scope))

    _tokens(web, monkeypatch)
    assert principal().admin is True                       # a fresh box: loopback is the owner
    store.revoke_all(revoke_env=True)
    assert principal().admin is False                      # the owner locked it: no longer


def test_the_offline_recovery_still_opens_the_admin_tier(monkeypatch, store):
    from agents import web

    _tokens(web, monkeypatch, admin="env-admin")
    store.revoke_all(revoke_env=True)
    fresh = store.rotate("admin")                          # python -m …token_store rotate admin
    with TestClient(web.app, client=LOOPBACK) as client:
        assert client.get("/api/admin/mcp").status_code == 401
        assert client.get("/api/admin/mcp", headers={"x-admin-token": fresh}).status_code == 200


# ── m1: a managed user token that expired still counts as configured ─────────────

def test_an_expired_managed_user_token_keeps_the_hub_locked(monkeypatch, store):
    from agents import web

    _tokens(web, monkeypatch)
    store.issue("user", ttl_days=1 / 86400)                # issued, never rotated: no flag
    time.sleep(1.2)
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert _both(client) == [401, 401]
    assert web._mcp_identity_check(None) is False


def test_an_issued_then_revoked_managed_token_is_the_recorded_residual(monkeypatch, store):
    """The store keeps no trace of an issued token revoked without --revoke-env, so that
    hub reads as never configured (recorded under H273 Known limits; closing it needs a
    persistent flag in token_store, which is the owner's security lane)."""
    from agents import web

    _tokens(web, monkeypatch)
    store.issue("user")
    store.revoke_all("user")
    assert web._user_credential_required() is False
    store.issue("user")
    store.revoke_all("user", revoke_env=True)
    assert web._user_credential_required() is True


# ── m2 / m4 (C3, C4): the CLI's admin token and what it says when it keeps it ────

def _cli_headers(url, *, user="usr"):
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

    HubClient(url, admin_token="adm", user_token=user, opener=opener).get("/api/status")
    return seen


@pytest.mark.parametrize("url", ["http://hub.lan:8080", "http://10.0.0.5:8080", "HTTP://[::2]:8080"])
def test_an_admin_only_cli_never_sends_the_admin_token_off_machine_in_clear(url):
    headers = _cli_headers(url, user="")
    assert "x-admin-token" not in headers and "x-user-token" not in headers


@pytest.mark.parametrize("url, here", [(u, h) for u, h in SPELLINGS
                                       if u.startswith("http") and u != "http://[::1:8080"])   # unparseable
def test_the_cli_sends_the_admin_token_by_the_same_loopback_rule(url, here):
    assert ("x-admin-token" in _cli_headers(url)) is here


def test_a_refused_admin_verb_says_the_token_was_withheld(monkeypatch):
    from agents.cli import nerva
    from agents.cli.client import HubError

    class _Err:
        def __init__(self):
            self.chunks = []

        def write(self, text):
            self.chunks.append(text)

    def refused(ns, ctx):
        raise HubError(401, "admin token required")

    monkeypatch.setitem(nerva._VERBS, "tools", refused)
    err = _Err()
    ctx = nerva.Context(environ={"NERVA_HUB_URL": "http://192.0.2.2:8080", "JARVIS_ADMIN_TOKEN": "adm"}, err=err)
    assert nerva.main(["tools"], context=ctx) == nerva.EXIT_AUTH
    said = "".join(err.chunks)
    assert "withheld" in said and "https" in said and "Set JARVIS_ADMIN_TOKEN" not in said
    err.chunks.clear()
    ctx = nerva.Context(environ={"NERVA_HUB_URL": "http://127.0.0.1:8080", "JARVIS_ADMIN_TOKEN": "adm"}, err=err)
    nerva.main(["tools"], context=ctx)
    assert "withheld" not in "".join(err.chunks)


# ── m3: one run-log for the supervisor and the coordinator ───────────────────────

def test_the_supervisor_writes_to_the_run_log_a_env_file_names(tmp_path, monkeypatch):
    from agents.core import env_provenance as ep
    from scripts import runtime_supervisor

    repo_env = tmp_path / "repo.env"
    repo_env.write_text(f"JARVIS_RUNTIME_LOG={tmp_path / 'from-env.jsonl'}\n", encoding="utf-8")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    monkeypatch.delenv("JARVIS_RUNTIME_LOG", raising=False)
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    assert runtime_supervisor._log_path() == tmp_path / "from-env.jsonl"
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(tmp_path / "from-process.jsonl"))
    assert runtime_supervisor._log_path() == tmp_path / "from-process.jsonl"


def test_hub_value_reads_both_layers_without_loading(tmp_path, monkeypatch):
    import os

    from agents.core import env_provenance as ep

    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("A_KEY=home\nB_KEY=home\n", encoding="utf-8")
    repo_env = tmp_path / "repo.env"
    repo_env.write_text(f"JARVIS_USER_HOME={home}\nA_KEY=repo\n", encoding="utf-8")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    env = {"C_KEY": "process"}
    assert [ep.hub_value(k, env) for k in ("A_KEY", "B_KEY", "C_KEY", "D_KEY")] == ["repo", "home", "process", None]
    assert "A_KEY" not in os.environ and "B_KEY" not in os.environ


# ── m4 (D1, D3): the coordinator's run() and the harness load before they read ──

class _Stop(Exception):
    pass


def test_the_coordinators_run_reads_its_run_log_from_the_env_file(tmp_path, monkeypatch):
    import asyncio
    import os

    from agents.core import env_provenance as ep
    from agents.core.observability import runtime_log
    from scripts import coordinator

    saved = dict(os.environ)
    try:
        repo_env = tmp_path / "repo.env"
        repo_env.write_text(f"JARVIS_RUNTIME_LOG={tmp_path / 'run.jsonl'}\n", encoding="utf-8")
        monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
        monkeypatch.setattr(ep, "_HUB_LOADED", None, raising=False)
        monkeypatch.delenv("JARVIS_RUNTIME_LOG", raising=False)
        monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
        seen = []
        real = runtime_log.default_log_path
        monkeypatch.setattr(runtime_log, "default_log_path", lambda: seen.append(real()) or seen[-1])

        async def build():
            raise _Stop

        monkeypatch.setattr(coordinator, "_build_orchestrator", build)
        with pytest.raises(_Stop):
            asyncio.run(coordinator.run())
        assert [str(p) for p in seen] == [str(tmp_path / "run.jsonl")]
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_the_reality_harness_loads_before_it_builds(monkeypatch):
    import asyncio

    from agents.core import env_provenance as ep
    from agents.core.observability import reality_evidence

    order = []

    def load():
        order.append("load")
        raise _Stop

    monkeypatch.setattr(ep, "load_hub_env", load)
    with pytest.raises(_Stop):
        asyncio.run(reality_evidence._run_and_record(None))
    assert order == ["load"]


# ── n1: a bare IPv6 hub is read the way http.client dials it ─────────────────────

@pytest.mark.parametrize("url, here", [
    ("http://0:0:0:0:0:0:0:1:8080", True), ("http://0:0:0:0:0:0:0:2:8080", False),
    ("http://fe80::1%eth0:8080", False), ("http://::1:8080", True), ("http://127.0.0.1:8080", True),
])
def test_a_bare_ipv6_hub_is_judged_by_the_address_dialled(url, here):
    from agents.cli import client
    from scripts import doctor

    assert client.is_loopback_url(url) is here
    assert doctor.is_loopback_url(url) is here
