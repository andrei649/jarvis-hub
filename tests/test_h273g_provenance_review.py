"""H273, the sixth review (review-H273g) — its findings, pinned.

- m1: "no local process mints its way back in" holds only where an admin credential was
  ever configured. A box that only ever had a user token keeps trusting a direct
  localhost caller as admin; that is now stated, and pinned so it stays deliberate.
- m2: the offline recovery wrote a tokens.db the hub never read when the data root was
  set only in a .env. ``scripts/token_recover.py`` loads the hub's .env first and says
  which store it wrote.
- m3: the CLI said "withheld" on refusals https would not fix, and ``nerva status`` still
  asked for the admin token that was set. One helper answers both, for the client that
  was refused.
- m4: a named-pipe .env gave the supervisor and the coordinator different run-logs. The
  supervisor tells its child the path it chose.
- m5: the survivors: an issued-only admin token, the generic hint, two ``hub_value``
  layer rules, and the supervisor run as a script.
- nits: the configured-scope check lists the token table once per store; nothing purges
  expired rows; an empty JARVIS_RUNTIME_LOG is unset on both ends.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_h273e_provenance_review import _both, _mcp_on
from tests.test_h273f_provenance_review import LOOPBACK, _mint, _tokens, store  # noqa: F401

REPO = Path(__file__).resolve().parents[1]


# ── m1: a box that never had an admin credential ─────────────────────────────────

def test_a_user_only_box_still_trusts_this_machine_as_admin(monkeypatch, store):
    """Deliberate and recorded: the user-token lock binds callers from other machines;
    ``revoke all --revoke-env`` closes it for this one too."""
    from agents import web

    _tokens(web, monkeypatch, user="env-user")
    store.revoke_all("user", revoke_env=True)
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert _both(client)[1] == 401                    # MCP asks for the user credential
        assert _mint(client).status_code == 200           # this machine is still admin


def test_the_docstrings_state_the_limit():
    from agents import web

    assert "binds remote callers only" in web._user_credential_required.__doc__
    assert "never had an admin credential keeps trusting" in web._admin_configured.__doc__


# ── m5 (G07): an admin token only ever issued ────────────────────────────────────

@pytest.mark.parametrize("expired", [False, True])
def test_an_issued_only_admin_token_closes_the_loopback_fallback(monkeypatch, store, expired):
    from agents import web

    _tokens(web, monkeypatch)
    store.issue("admin", ttl_days=1 / 86400 if expired else None)
    if expired:
        time.sleep(1.2)
    with TestClient(web.app, client=LOOPBACK) as client:
        assert client.get("/api/admin/mcp").status_code == 401
        assert _mint(client).status_code == 401


# ── n1: the table is listed once per store ───────────────────────────────────────

def test_a_configured_scope_is_remembered_per_store(monkeypatch, store):
    from agents import web

    store.issue("user")
    calls = []
    real = store.list_tokens

    def counted():
        calls.append(1)
        return real()

    monkeypatch.setattr(store, "list_tokens", counted)
    assert all(web._ever_configured("user") for _ in range(5))
    assert len(calls) == 1
    assert web._ever_configured("admin") is False and web._ever_configured("admin") is False
    assert len(calls) == 3                                   # a scope never seen is asked every time


def test_nothing_in_the_hub_purges_expired_tokens():
    """The token store's ``purge_expired`` would empty the record of a configured tier
    (review-H273g n2): no hub code calls it. (Other stores have methods of that name.)"""
    hits = []
    for path in (REPO / "agents").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name != "token_store.py" and "token_store" in text and "purge_expired(" in text:
            hits.append(path)
    assert hits == []


# ── m2: recovery writes the store the hub reads ──────────────────────────────────

def test_recovery_writes_the_store_a_env_file_names(tmp_path, monkeypatch, capsys):
    from agents.core import env_provenance as ep
    from agents.core import paths
    from agents.core.security import token_store as ts_mod
    from scripts import token_recover

    home = tmp_path / "home"
    repo_env = tmp_path / "repo.env"
    repo_env.write_text(f"JARVIS_USER_HOME={home}\n", encoding="utf-8")    # set only in the .env
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    monkeypatch.setattr(ep, "_HUB_LOADED", None)
    monkeypatch.setattr(ts_mod, "_store", None)
    monkeypatch.setattr(paths, "_DEFAULT_ROOT", tmp_path / "default-root")   # never the checkout's
    for key in ("JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_USER_HOME"):
        # setenv first, so the teardown puts back the environment as it was even for a
        # key the load sets: a delenv of an unset key records nothing, and the loaded
        # JARVIS_USER_HOME leaked into every later test on the worker.
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    assert token_recover.main(["rotate", "admin"]) == 0
    out, err = capsys.readouterr()
    db = home / "memory" / "security" / "tokens.db"
    assert db.is_file() and str(db) in err
    assert ts_mod.TokenStore(db_path=str(db)).verify(out.strip()) == "admin"


# ── m3: the hint, for the client that was refused ────────────────────────────────

class _Err:
    def __init__(self):
        self.chunks = []

    def write(self, text):
        self.chunks.append(text)


def _refused_hint(monkeypatch, environ, status=401):
    from agents.cli import nerva
    from agents.cli.client import HubError

    def refused(ns, ctx):
        raise HubError(status, "refused")

    monkeypatch.setitem(nerva._VERBS, "tools", refused)
    err = _Err()
    assert nerva.main(["tools"], context=nerva.Context(environ=environ, err=err)) == nerva.EXIT_AUTH
    return "".join(err.chunks)


def test_a_withheld_admin_token_is_one_cause_the_user_token_the_other(monkeypatch):
    said = _refused_hint(monkeypatch, {"NERVA_HUB_URL": "http://192.0.2.2:8080", "JARVIS_ADMIN_TOKEN": "adm"}, 403)
    assert "withheld" in said and "JARVIS_USER_TOKEN" in said and "If this needs the admin token" in said


def test_with_no_admin_token_set_the_hint_is_the_generic_one(monkeypatch):
    # A user token that is set is named as refused, never asked for (review-H273h m3).
    said = _refused_hint(monkeypatch, {"NERVA_HUB_URL": "http://192.0.2.2:8080", "JARVIS_USER_TOKEN": "u"})
    assert "withheld" not in said and "refused JARVIS_USER_TOKEN" in said and "token_recover.py" in said


def test_the_hint_is_built_for_the_client_that_was_refused(monkeypatch):
    from agents.cli import nerva
    from agents.cli.client import HubClient, HubError

    def refused(ns, ctx):
        raise HubError(401, "refused")

    monkeypatch.setitem(nerva._VERBS, "tools", refused)
    err = _Err()
    here = HubClient.from_env({"NERVA_HUB_URL": "http://192.0.2.2:8080", "JARVIS_ADMIN_TOKEN": "adm"})
    ctx = nerva.Context(environ={}, err=err, client_factory=lambda env: here)
    nerva.main(["tools"], context=ctx)
    assert "withheld" in "".join(err.chunks)


def test_status_never_asks_for_the_admin_token_that_is_set():
    from agents.cli import nerva
    from agents.cli.client import HubClient

    withheld = HubClient.from_env({"NERVA_HUB_URL": "http://192.0.2.2:8080", "JARVIS_ADMIN_TOKEN": "adm"})
    line = nerva._runnable_line({"reason": "needs_token"}, withheld)
    assert "JARVIS_ADMIN_TOKEN is withheld" in line and "JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN" not in line
    plain = HubClient.from_env({"NERVA_HUB_URL": "http://127.0.0.1:8080"})
    assert nerva._read_hint(plain) == "(needs JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN to read)"


# ── m4, n4: one run-log whatever layer named it ──────────────────────────────────

@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes")
def test_a_named_pipe_env_leaves_one_run_log(tmp_path, monkeypatch):
    from agents.core import env_provenance as ep
    from agents.core.observability import runtime_log
    from scripts import runtime_supervisor

    repo_env = tmp_path / "repo.env"
    os.mkfifo(repo_env)
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    monkeypatch.delenv("JARVIS_RUNTIME_LOG", raising=False)
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    child = runtime_supervisor._child_env()
    # The child reads the pipe itself, as the hub does: nothing is handed down, and the
    # two agree (tests/test_h273h_provenance_review.py; review-H273h m1).
    assert "JARVIS_RUNTIME_LOG" not in child
    assert str(runtime_supervisor._log_path()) == runtime_log.DEFAULT_LOG_PATH


def test_the_child_is_told_the_path_a_env_file_names(tmp_path, monkeypatch):
    from agents.core import env_provenance as ep
    from scripts import runtime_supervisor

    repo_env = tmp_path / "repo.env"
    repo_env.write_text(f"JARVIS_RUNTIME_LOG={tmp_path / 'from-env.jsonl'}\n", encoding="utf-8")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    monkeypatch.delenv("JARVIS_RUNTIME_LOG", raising=False)
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    spawned = []

    class Popen:
        def __init__(self, argv, env=None):
            spawned.append(env)

    monkeypatch.setattr(runtime_supervisor.subprocess, "Popen", Popen)
    runtime_supervisor._spawn()
    assert spawned[0]["JARVIS_RUNTIME_LOG"] == str(tmp_path / "from-env.jsonl")


def test_an_empty_run_log_value_is_unset_on_both_ends(monkeypatch):
    from agents.core.observability import runtime_log
    from scripts import runtime_supervisor

    monkeypatch.setenv("JARVIS_RUNTIME_LOG", "")
    assert runtime_log.default_log_path() == Path(runtime_log.DEFAULT_LOG_PATH) == runtime_supervisor._log_path()


# ── m5 (G17, G19): hub_value's layer rules ───────────────────────────────────────

def test_dotenv_disabled_in_the_repo_env_hides_the_home_layer_too(tmp_path, monkeypatch):
    from agents.core import env_provenance as ep

    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("KEY=home\n", encoding="utf-8")
    repo_env = tmp_path / "repo.env"
    repo_env.write_text("PYTHON_DOTENV_DISABLED=1\n", encoding="utf-8")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    assert ep.hub_value("KEY", {"JARVIS_USER_HOME": str(home)}) is None


def test_a_home_value_interpolates_from_the_repo_layer(tmp_path, monkeypatch):
    from agents.core import env_provenance as ep

    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("LOGP=${BASE}/log\n", encoding="utf-8")
    repo_env = tmp_path / "repo.env"
    repo_env.write_text(f"BASE=/x\nJARVIS_USER_HOME={home}\n", encoding="utf-8")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    assert ep.hub_value("LOGP", {}) == "/x/log"


# ── m5 (G21): run as a script, the supervisor still reads the .env layer ─────────

def test_the_supervisor_run_as_a_script_can_import_the_app(tmp_path):
    code = (
        "import sys, runpy\n"
        f"sys.path = [p for p in sys.path if p not in ('', {str(REPO)!r})]\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        f"g = runpy.run_path({str(REPO / 'scripts' / 'runtime_supervisor.py')!r})\n"
        "g['_log_path']()\n"
        "print('agents.core.env_provenance' in sys.modules)\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("JARVIS_RUNTIME_LOG", "PYTHONPATH")}
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,  # noqa: S603
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "True", out.stderr


def test_nerva_status_names_the_withheld_token_on_both_lines():
    import io

    from agents.cli import nerva
    from agents.cli.client import HubError

    class Refused:
        base_url = "http://192.0.2.2:8080"
        admin_token = "adm"

        def _sends_admin_token(self):
            return False

        def get(self, path, *args, **kwargs):
            if path == "/status":
                return {"version": "1", "agents": []}
            raise HubError(401, "user token required")

        post = get

    out = io.StringIO()
    ctx = nerva.Context(environ={}, out=out, client_factory=lambda env: Refused())
    assert nerva.main(["status"], context=ctx) == nerva.EXIT_OK
    lines = [line for line in out.getvalue().splitlines() if "runnable:" in line or "e-stop:" in line]
    assert len(lines) == 2 and all("JARVIS_ADMIN_TOKEN is withheld" in line for line in lines)
