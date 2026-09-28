"""H273 third review round: the start reads .env before anything else, and every
"in effect" answer is true.

The third review of H273 found two majors:

- **M2. The before-load note covered the import, not the start.** The lifespan read 31
  more Nerva names before the .env files were loaded: the boot guards, logging,
  ``Orchestrator(...)`` with its audit log, memory and budget ledger, and
  ``llm_router.detect()``. So ten knobs set in a .env were not in effect while the
  route and the doctor said they were: the audit key, the public-profile seed gate, the
  budget, turn embeddings, the router's URLs and keys. Two read-again entries were false
  as well: the tokens in the bind guard, and the OAuth ids behind a second copy of the
  module. Now serve.py and the lifespan load the .env files first, once per process
  (a named pipe is read once), and what locates the hub's own files is taken from the
  process environment only.
- **M3. The MCP transport checked the user token frozen at import.** With the token
  only in .env, a local process drove the assistant without it and a remote client that
  presented it was refused.

The minors and nits follow the majors below.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agents.core.env_provenance as ep

ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = ("127.0.0.1", 50000)
REMOTE = ("192.168.1.50", 50000)


@pytest.fixture
def env_home(tmp_path, monkeypatch):
    """A data home whose .env holds the given keys, none of them in the environment yet;
    each test starts as a fresh process would, with nothing loaded. The repo layer is an
    absent file (a developer's own .env stays out), and whatever the load puts in the
    environment is taken back out."""
    saved = dict(os.environ)
    monkeypatch.setattr(ep, "REPO_ENV_FILE", tmp_path / "no-repo" / ".env", raising=False)

    def make(values: dict[str, str]) -> Path:
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        (home / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        monkeypatch.setenv("JARVIS_USER_HOME", str(home))
        for key in values:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(ep, "_HUB_LOADED", None, raising=False)
        return home

    yield make
    os.environ.clear()
    os.environ.update(saved)


def _owned(names: set[str]) -> set[str]:
    from scripts import doctor

    declared = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(encoding="utf-8"),
                              re.M))
    hub_names = doctor.hub_env_names(ROOT)
    return {name for name in names if name.startswith(("JARVIS_", "NERVA_", "NEO4J_"))
            or name in declared or name in hub_names}


# ── M2: nothing the start reads comes before the load ────────────────────────────

_START_SPY = r"""
import json, os, sys
reads = {"before": [], "after": []}
phase = ["before"]
original = os._Environ.__getitem__
def spy(self, key):
    reads[phase[0]].append(key)
    return original(self, key)
os._Environ.__getitem__ = spy
import agents.web
import agents.core.env_provenance as ep
real = ep.load_layered_env
def marked(*args, **kwargs):
    phase[0] = "after"
    return real(*args, **kwargs)
ep.load_layered_env = marked
import agents.core.plugin_manager as pm
if hasattr(pm, "load_layered_env"):
    pm.load_layered_env = marked
from fastapi.testclient import TestClient
with TestClient(agents.web.app):
    pass
os._Environ.__getitem__ = original
print("SPY" + json.dumps({key: sorted({n for n in value if isinstance(n, str)}) for key, value in reads.items()}))
"""


def _reads_before_the_load(tmp_path, data_root: str) -> tuple[set[str], set[str]]:
    env = {key: value for key, value in os.environ.items() if key not in ("JARVIS_HOME", "JARVIS_USER_HOME")}
    env.update({data_root: str(tmp_path / data_root), "PYTHONDONTWRITEBYTECODE": "1"})
    out = subprocess.run([sys.executable, "-c", _START_SPY], cwd=ROOT, env=env, capture_output=True,
                         text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    reads = json.loads(out.stdout.rsplit("SPY", 1)[1])
    assert reads["after"], "the load never ran"
    return set(reads["before"]), set(reads["after"])


# Two whole hub starts in subprocesses: ~16 s alone, past the suite's 30 s backstop on a
# loaded machine (the thread-method timeout then takes the xdist worker down with it).
@pytest.mark.timeout(240)
def test_the_start_reads_nothing_of_its_own_before_the_env_files_are_loaded(tmp_path):
    """The whole start is measured, not only the import: the lifespan up to the load, with
    the data root set either way (without JARVIS_HOME the import reads the data home's
    names instead). Every entry of READ_BEFORE_LOAD must be read before the load in one of
    the two, or it is stale."""
    classified = ep.READ_BEFORE_LOAD | ep.READ_AGAIN_AFTER_LOAD | set(ep.SPLIT_NOTES) | {"PYTHON_DOTENV_DISABLED"}
    seen_before: set[str] = set()
    for data_root in ("JARVIS_HOME", "JARVIS_USER_HOME"):
        before, _after = _reads_before_the_load(tmp_path, data_root)
        seen_before |= before
        unclassified = _owned(before) - classified
        assert not unclassified, (
            f"{sorted(unclassified)} are read before the .env files are loaded ({data_root} set). Load "
            "them first, or classify each in env_provenance (READ_BEFORE_LOAD when a .env value cannot "
            "be in effect).")
    stale = ep.READ_BEFORE_LOAD - seen_before
    assert not stale, f"{sorted(stale)} are listed as read before the load, and are not"
    assert not set(ep.SPLIT_NOTES) - seen_before


def test_serve_py_builds_the_server_from_a_port_in_the_env_file(env_home, monkeypatch):
    import uvicorn

    env_home({"JARVIS_PORT": "9137"})
    import serve

    built = []
    monkeypatch.setattr(serve, "probe_bind", lambda *_a, **_k: None)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, *_a, **_k: built.append(self.config.port))
    serve.main()
    assert built == [9137]


@pytest.mark.parametrize("key, value, in_effect", [
    ("JARVIS_AUDIT_KEY", "k" * 32, lambda orch: orch.audit._key is not None),
    ("JARVIS_BUDGET_MAX_TOKENS", "5000", lambda orch: orch.budget_ledger is not None),
    ("MEMORY_EMBED_TURNS", "true", lambda orch: orch.memory.embed_turns is True),
    ("GEMINI_API_KEY", "g-from-dotenv", lambda orch: orch.llm_router._gemini_pool.size > 0),
])
def test_a_knob_the_start_reads_takes_its_value_from_the_env_file(env_home, key, value, in_effect):
    from agents import web

    env_home({key: value})
    with TestClient(web.app, client=LOOPBACK):
        assert in_effect(web.orch), f"{key} set only in the data home's .env is not in effect"


def test_the_bind_guard_takes_a_token_from_the_env_file(env_home, monkeypatch):
    """serve.py loads the files before it builds the server, so the token in .env is
    one: the hub starts on an external address instead of refusing."""
    import uvicorn

    env_home({"JARVIS_USER_TOKEN": "tok-from-dotenv"})
    monkeypatch.setenv("JARVIS_HOST", "0.0.0.0")
    import serve

    monkeypatch.setattr(serve, "probe_bind", lambda *_a, **_k: None)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, *_a, **_k: None)
    serve.main()


def test_the_lifespan_guard_takes_a_token_from_the_env_file(env_home, monkeypatch):
    """The raw-uvicorn entry: the lifespan loads the files before its boot guards."""
    from agents import web

    env_home({"JARVIS_USER_TOKEN": "tok-from-dotenv"})
    monkeypatch.setenv("JARVIS_HOST", "0.0.0.0")
    with TestClient(web.app, client=LOOPBACK) as client:
        assert client.get("/health").status_code < 500


def test_a_bot_token_only_in_the_env_file_is_judged_by_the_boot_guards(env_home, monkeypatch):
    """The late front-door pass is gone because the early one now sees the files: an
    unguarded bot that lives only in .env still refuses the start."""
    from agents import web

    for key in ("TELEGRAM_ALLOWED_USER_IDS", "JARVIS_CHANNEL_OPEN"):
        monkeypatch.delenv(key, raising=False)
    env_home({"TELEGRAM_BOT_TOKEN": "123456:dotenv-only-token", "JARVIS_CHANNEL_PAIRING": "0"})

    async def start():
        async with web.lifespan(web.app):
            pass

    with pytest.raises(SystemExit) as refused:
        asyncio.run(start())
    assert "telegram bot would answer any sender" in str(refused.value)


def test_the_repl_loads_the_env_files_before_it_builds_anything(env_home, monkeypatch):
    """agents/run.py, the other entry: the files come before its orchestrator is made."""
    import agents.run as run

    class _Stop(Exception):
        pass

    seen = []

    def config():
        seen.append(ep._HUB_LOADED is not None and os.environ.get("PROV_REPL_KEY") == "1")
        raise _Stop

    monkeypatch.setattr(run, "JarvisConfig", config)
    env_home({"PROV_REPL_KEY": "1"})
    with pytest.raises(_Stop):
        asyncio.run(run.main())
    assert seen == [True]


_REDACTION_SPY = r"""
import os, sys
from pathlib import Path
import agents.core.env_provenance as ep
ep.REPO_ENV_FILE = Path(sys.argv[1])
ep.load_hub_env()
from agents.core.security import log_redaction
print("ENABLED", log_redaction._ENABLED, os.environ.get("JARVIS_LOG_REDACTION"))
"""


def test_a_env_file_cannot_switch_log_redaction_off(tmp_path):
    """The redaction floor is the boot environment's alone (log_redaction snapshots it
    on purpose): loading the files first must not hand it to a file."""
    repo_env = tmp_path / ".env"
    repo_env.write_text("JARVIS_LOG_REDACTION=0\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key != "JARVIS_LOG_REDACTION"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    out = subprocess.run([sys.executable, "-c", _REDACTION_SPY, str(repo_env)], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.split()[-3:] == ["ENABLED", "True", "0"]      # loaded, and not in effect
    assert "JARVIS_LOG_REDACTION" in ep.READ_BEFORE_LOAD


def test_the_hub_loads_its_files_once_per_process(env_home, monkeypatch):
    """A named pipe is read once: serve.py, the lifespan and the plugin manager all ask,
    the first one loads."""
    calls = []
    real = ep.load_layered_env
    monkeypatch.setattr(ep, "load_layered_env", lambda *a: calls.append(a) or real(*a))
    env_home({"PROV_ONCE_KEY": "1"})
    first = ep.load_hub_env()
    assert ep.load_hub_env() is first and len(calls) == 1
    assert os.environ["PROV_ONCE_KEY"] == "1"


@pytest.mark.parametrize("key", ["JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_APP_ROOT"])
def test_a_root_named_only_in_an_env_file_is_recorded_and_not_set(env_home, monkeypatch, key):
    """What locates the hub's own files is read while it is imported, before any file
    can be: a .env value would split its stores between two roots. It is recorded, with
    the note, and never put in the environment."""
    from agents.core import paths

    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.delenv("JARVIS_APP_ROOT", raising=False)
    env_home({key: "/somewhere/else"})
    roots = (paths.data_root(), paths.app_root())
    ep.load_hub_env()
    assert key not in os.environ and (paths.data_root(), paths.app_root()) == roots
    row = ep.provenance()[key]
    assert row["layer"] == ep.USER_ENV and "not in effect" in ep.note_for(key, row["layer"])


def test_a_refused_root_in_both_files_keeps_the_first_files_row(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_APP_ROOT", raising=False)
    repo, home = tmp_path / "repo.env", tmp_path / "home.env"
    repo.write_text("JARVIS_APP_ROOT=/from/repo\n", encoding="utf-8")
    home.write_text("JARVIS_APP_ROOT=/from/home\n", encoding="utf-8")
    ep.load_layered_env(repo, home)
    assert "JARVIS_APP_ROOT" not in os.environ
    assert ep.provenance()["JARVIS_APP_ROOT"] == {"layer": ep.REPO_ENV, "shadowed": [ep.USER_ENV]}


def test_a_refused_root_set_later_while_running_is_not_the_files(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_APP_ROOT", raising=False)
    repo = tmp_path / "repo.env"
    repo.write_text("JARVIS_APP_ROOT=/from/repo\n", encoding="utf-8")
    ep.load_layered_env(repo, None)
    monkeypatch.setenv("JARVIS_APP_ROOT", "/set/while/running")
    assert ep.provenance()["JARVIS_APP_ROOT"]["layer"] == ep.RUNTIME


def test_the_prediction_of_the_repo_layer_leaves_a_refused_root_out(tmp_path):
    repo = tmp_path / ".env"
    repo.write_text("JARVIS_HOME=/elsewhere\nJARVIS_USER_HOME=/named/home\n", encoding="utf-8")
    merged = ep.after_repo_layer(repo, {})
    assert "JARVIS_HOME" not in merged and merged["JARVIS_USER_HOME"] == "/named/home"


def test_a_last_binding_without_a_value_sets_nothing_in_the_prediction_either(tmp_path, monkeypatch):
    repo = tmp_path / ".env"
    repo.write_text("PROV_BARE=1\nPROV_BARE\n", encoding="utf-8")
    monkeypatch.delenv("PROV_BARE", raising=False)
    predicted = ep.after_repo_layer(repo, {})
    try:
        ep.load_layered_env(repo, None)
        assert "PROV_BARE" not in predicted and "PROV_BARE" not in os.environ
    finally:
        os.environ.pop("PROV_BARE", None)


def test_the_data_home_named_in_the_repo_env_says_what_it_does_not_reach():
    note = ep.note_for("JARVIS_USER_HOME", ep.REPO_ENV)
    assert "process environment" in note and ep.note_for("JARVIS_USER_HOME", ep.PROCESS) == ""


# ── M3: the MCP transport reads the user token the way every route does ─────────

def _mcp_on(web, monkeypatch):
    orig = web.orch.get_setting

    def fake(key, default=None):
        if key == "mcp.server_enabled":
            return True
        if key == "mcp.oauth_required":
            return False
        return orig(key, default)

    monkeypatch.setattr(web.orch, "get_setting", fake)


_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def test_a_user_token_from_the_env_file_guards_the_mcp_transport_on_this_machine(monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "")                     # frozen at import, before any load
    monkeypatch.setenv("JARVIS_USER_TOKEN", "tok-from-dotenv")      # as the load puts it
    with TestClient(web.app, client=LOOPBACK) as client:
        _mcp_on(web, monkeypatch)
        assert client.post("/api/mcp/server/rpc", json=_LIST).status_code == 401
        ok = client.post("/api/mcp/server/rpc", json=_LIST, headers={"x-user-token": "tok-from-dotenv"})
        assert ok.status_code == 200


def test_a_user_token_from_the_env_file_lets_a_remote_client_in(monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "tok-from-dotenv")
    with TestClient(web.app, client=REMOTE) as client:
        _mcp_on(web, monkeypatch)
        ok = client.post("/api/mcp/server/rpc", json=_LIST, headers={"x-user-token": "tok-from-dotenv"})
        assert ok.status_code == 200
        assert client.post("/api/mcp/server/rpc", json=_LIST).status_code == 401


# ── the OAuth ids: one module, initialised after the load ────────────────────────

def test_the_oauth_routes_use_client_ids_from_the_env_file(env_home):
    from agents import web

    env_home({"GOOGLE_CLIENT_ID": "g-id-from-dotenv", "SPOTIFY_CLIENT_ID": "s-id-from-dotenv"})
    with TestClient(web.app, client=LOOPBACK) as client:
        google = client.get("/api/oauth/auth-url", params={"service": "gmail"}).json()["url"]
        spotify = client.get("/api/oauth/auth-url", params={"service": "spotify"}).json()["url"]
    assert "client_id=g-id-from-dotenv&" in google and "client_id=s-id-from-dotenv&" in spotify


# ── m1: the admin token goes only to a hub on this machine, decided by address ───

@pytest.mark.parametrize("url, here", [
    ("http://127.0.0.1:8080", True), ("http://127.0.0.2:8080", True), ("http://127.1:8080", True),
    ("http://2130706433:8080", True), ("http://localhost.:8080", True), ("http://LOCALHOST:8080", True),
    ("http://[::1]:8080", True), ("http://[::ffff:127.0.0.1]:8080", True),
    ("http://hub.lan:8080", False), ("http://10.0.0.5:8080", False), ("http://[::2]:8080", False),
    ("file:///tmp/x", False), ("data:text/plain,ok", False), ("http://:8080", False),
])
def test_this_machine_is_decided_by_address_not_by_spelling(url, here):
    from scripts import doctor

    assert doctor.is_loopback_url(url) is here


def _recording_hub(seen, *, model=None):
    import urllib.error

    class _Resp:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def close(self):
            pass

    def opener(request, timeout=None):
        url = getattr(request, "full_url", request)
        headers = {k.lower(): v for k, v in dict(getattr(request, "headers", {}) or {}).items()}
        seen.append((url, headers))
        if url.endswith("/readyz"):
            return _Resp(b"ok")
        if model is None:
            raise urllib.error.HTTPError(url, 401, "token required", {}, None)
        return _Resp(json.dumps({"model": model}).encode("utf-8"))
    return opener


@pytest.mark.parametrize("hub, sent", [
    ("http://127.0.0.2:8080", {"x-admin-token": "adm-r1"}),     # this machine, however spelled
    ("http://hub.lan:8080", {}),                                # another machine: the admin token stays
])
def test_the_route_read_sends_the_admin_token_only_to_this_machine(hub, sent):
    from scripts import doctor

    seen = []
    env = {"NERVA_HUB_URL": hub, "JARVIS_ADMIN_TOKEN": "adm-r1"}
    opener = _recording_hub(seen)
    readyz = doctor.check_readyz(opener, env=env)
    check = doctor.check_runtime_resolves(opener, readyz=readyz, env=env)
    route = [headers for url, headers in seen if url.endswith("/api/onboarding/command-center")]
    assert route and {k: v for k, v in route[0].items() if k.startswith("x-")} == sent
    assert check.reason == "needs_token"
    if not sent:
        assert "JARVIS_USER_TOKEN" in check.detail and "this machine" in check.detail


def test_a_user_token_goes_to_any_hub():
    from scripts import doctor

    headers = doctor._hub_headers({"JARVIS_USER_TOKEN": "usr", "JARVIS_ADMIN_TOKEN": "adm"}, "http://hub.lan:8080")
    assert headers.get("x-user-token") == "usr" and "x-admin-token" not in headers


@pytest.mark.parametrize("hub", ["file://{tmp}", "data:text/plain,ok#"])
def test_a_hub_address_that_is_not_http_is_named_not_a_crash(tmp_path, hub):
    """n5: file: and data: URLs reached urlopen and crashed check_readyz on a reply with
    no status; hub_open refuses anything but http and https."""
    from scripts import doctor

    (tmp_path / "readyz").write_text("ok", encoding="utf-8")
    check = doctor.check_readyz(env={"NERVA_HUB_URL": hub.format(tmp=tmp_path)})
    assert check.reason == "hub_url_invalid"


def test_hub_open_always_has_a_timeout():
    """n10: None meant "wait forever" for a direct caller."""
    import inspect

    from scripts import doctor

    default = inspect.signature(doctor.hub_open).parameters["timeout"].default
    assert isinstance(default, (int, float)) and default > 0


# ── m2: every printed name is an identifier, a prefixed one too ─────────────────

def test_a_prefixed_name_with_control_characters_is_counted_not_printed(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    (root).mkdir()
    (root / ".env").write_text("JARVIS_\x1b]0;pwned\x07TITLE=1\nNERVA_\x1b[2JCLEAR=1\nJARVIS_\x08\x08OK=1\n"
                               "JARVIS_PLAIN_KNOB=1\n", encoding="utf-8")
    check = doctor.check_config_sources(root, {})
    text = f"{check.reason} {check.detail} {json.dumps(check.data)}"
    assert not any(ch in text for ch in "\x1b\x07\x08")
    assert "withheld_env_names:3" in check.reason
    assert "JARVIS_PLAIN_KNOB" in [row["key"] for row in check.data["sources"]]


def test_a_hub_row_with_control_characters_is_not_printed(tmp_path):
    from scripts import doctor

    payload = {"sources": [{"key": "JARVIS_\x1b[2JCLEAR", "layer": "repo_env", "shadowed": []},
                           {"key": "NERVA_\x1b]0;pwned\x07T", "layer": "repo_env", "shadowed": []}],
               "files": {}}
    opener = _sources_hub(payload)
    env = {"NERVA_HUB_URL": "http://127.0.0.1:8080"}
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=doctor.check_readyz(opener, env=env))
    text = f"{check.reason} {check.detail} {json.dumps(check.data)}"
    assert not any(ch in text for ch in "\x1b\x07") and check.data["sources"] == []


# ── m3: hub mode on this machine reads the hub's own files; empty is a name ─────

def _sources_hub(payload, *, refuse=None):
    import urllib.error

    class _Resp:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def close(self):
            pass

    def opener(request, timeout=None):
        url = getattr(request, "full_url", request)
        headers = {k.lower(): v for k, v in dict(getattr(request, "headers", {}) or {}).items()}
        if url.endswith("/readyz"):
            return _Resp(b"ok")
        if refuse is not None and "x-admin-token" not in headers:
            raise urllib.error.HTTPError(url, refuse, "refused", {}, None)
        return _Resp(json.dumps(payload).encode("utf-8"))
    return opener


def test_hub_mode_on_this_machine_shows_a_plain_custom_key_and_an_empty_placeholder(tmp_path):
    from scripts import doctor

    repo_env = tmp_path / ".env"
    repo_env.write_text("MY_TOOL_FLAG=on\nNTFY_TOPIC=\nGEZDGNBVGY3TQOJQ====\n", encoding="utf-8")
    payload = {"sources": [{"key": key, "layer": "repo_env", "shadowed": []}
                           for key in ("MY_TOOL_FLAG", "NTFY_TOPIC", "GEZDGNBVGY3TQOJQ")],
               "files": {"repo_env": {"path": str(repo_env), "present": True, "kind": "file", "read": True}}}
    opener = _sources_hub(payload)
    env = {"NERVA_HUB_URL": "http://127.0.0.1:8080"}
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=doctor.check_readyz(opener, env=env))
    shown = [row["key"] for row in check.data["sources"]]
    assert "MY_TOOL_FLAG" in shown and "NTFY_TOPIC" in shown and "GEZDGNBVGY3TQOJQ" not in shown
    assert "withheld_env_names:1" in check.reason


def test_hub_mode_on_another_machine_says_why_it_shows_only_known_names(tmp_path):
    from scripts import doctor

    payload = {"sources": [{"key": "MY_TOOL_FLAG", "layer": "repo_env", "shadowed": []},
                           {"key": "JARVIS_MODEL", "layer": "repo_env", "shadowed": []}],
               "files": {"repo_env": {"path": "/srv/nerva/.env", "present": True, "kind": "file", "read": True}}}
    opener = _sources_hub(payload)
    env = {"NERVA_HUB_URL": "http://hub.lan:8080"}
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=doctor.check_readyz(opener, env=env))
    assert [row["key"] for row in check.data["sources"]] == ["JARVIS_MODEL"]
    assert check.status == doctor.OK and "withheld" not in check.reason
    assert "another machine" in check.reason


def test_hub_mode_on_this_machine_keeps_the_repo_value_as_the_hub_does(tmp_path):
    from scripts import doctor

    repo_env, home_env = tmp_path / "repo.env", tmp_path / "home.env"
    repo_env.write_text("SEEDLINE===\n", encoding="utf-8")
    home_env.write_text("SEEDLINE=a-real-value\n", encoding="utf-8")
    payload = {"sources": [{"key": "SEEDLINE", "layer": "repo_env", "shadowed": ["user_env"]}],
               "files": {"repo_env": {"path": str(repo_env), "present": True, "kind": "file", "read": True},
                         "user_env": {"path": str(home_env), "present": True, "kind": "file", "read": True}}}
    opener = _sources_hub(payload)
    env = {"NERVA_HUB_URL": "http://127.0.0.1:8080"}
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=doctor.check_readyz(opener, env=env))
    assert check.data["sources"] == [] and "withheld_env_names:1" in check.reason


def test_hub_mode_withholds_a_name_whose_value_it_cannot_read(tmp_path):
    """The hub names a .env key the doctor cannot find in the file the hub names (the
    file changed after the hub loaded it). With no value to judge, the name is counted,
    never printed as though it had a plain one."""
    from scripts import doctor

    repo_env = tmp_path / ".env"
    repo_env.write_text("", encoding="utf-8")
    payload = {"sources": [{"key": "MY_TOOL_FLAG", "layer": "repo_env", "shadowed": []}],
               "files": {"repo_env": {"path": str(repo_env), "present": True, "kind": "file", "read": True}}}
    opener = _sources_hub(payload)
    env = {"NERVA_HUB_URL": "http://127.0.0.1:8080"}
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=doctor.check_readyz(opener, env=env))
    assert check.data["sources"] == [] and "withheld_env_names:1" in check.reason


def test_a_first_run_data_home_is_scaffolded_before_its_env_is_read(env_home, tmp_path, monkeypatch):
    home = tmp_path / "first-run-home"
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))
    ep.load_hub_env()
    assert (home / ".env").is_file() and ep.files()["user_env"]["read"] is True


def test_prediction_mode_treats_an_empty_value_as_a_name(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("COMPOSE_PROFILES=\nPGSSLMODE=\n", encoding="utf-8")
    check = doctor.check_config_sources(root, {})
    assert {"COMPOSE_PROFILES", "PGSSLMODE"} <= {row["key"] for row in check.data["sources"]}
    assert check.status == doctor.OK


@pytest.mark.parametrize("line", ["d41d8cd98f00b204e9800998ecf8427e=", "d41d8cd98f00b204e9800998ecf8427e=1",
                                  "AKIAIOSFODNN7EXAMPLE=wJalrXUtnFEMI", "JBSWY3DPEHPK3PXP====GEZDGNBVGY3TQOJQ",
                                  "KRSXG5CTMVRXEZLUKN2XAZLSKNSWG4TF======#x"])
def test_a_name_shaped_like_value_material_is_counted_whatever_follows_it(tmp_path, line):
    """n2 and the empty-value rule together: a digest, a seed or an access key id on a
    line of its own is never printed, with or without text after its "="."""
    from scripts import doctor

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text(line + "\n", encoding="utf-8")
    check = doctor.check_config_sources(root, {})
    key = line.split("=", 1)[0]
    assert key not in doctor.format_report(doctor.DoctorReport(ok=True, root=str(root), checks=[check]))
    assert "withheld_env_names:1" in check.reason


# ── m4: the names Nerva reads through a pool, a descriptor or a private constant ─

def test_the_shell_view_sees_every_name_the_hub_reads():
    from scripts import doctor

    names = doctor.hub_env_names(ROOT)
    assert {"ANTHROPIC_API_KEYS", "GEMINI_API_KEYS", "OPENAI_BASE_URL", "OPENROUTER_BASE_URL",
            "SSL_CERT_FILE"} <= names


# ── m5: the reviewer's surviving mutants ────────────────────────────────────────

_AFTER_SPY = r"""
import json, os, sys
reads = {"before": [], "after": []}
phase = ["before"]
original = os._Environ.__getitem__
def spy(self, key):
    reads[phase[0]].append(key)
    return original(self, key)
os._Environ.__getitem__ = spy
import agents.web
import agents.core.env_provenance as ep
reads["loading"] = []
real = ep.load_layered_env
def marked(*args, **kwargs):
    phase[0] = "loading"           # the loader walks the whole environment: not a use
    try:
        return real(*args, **kwargs)
    finally:
        phase[0] = "after"
ep.load_layered_env = marked
from fastapi.testclient import TestClient
with TestClient(agents.web.app, client=("127.0.0.1", 50000)) as client:
    client.get("/health")
    client.get("/api/admin/settings")
    client.post("/api/mcp/server/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    client.get("/api/oauth/auth-url", params={"service": "gmail"})
    client.post("/sandbox/execute", json={"code": "print(1)"})
os._Environ.__getitem__ = original
print("SPY" + json.dumps({key: sorted({n for n in value if isinstance(n, str)}) for key, value in reads.items()}))
"""


def test_each_list_says_where_the_value_is_used(tmp_path):
    """E23/E24: the lists are measured by where each name is read, not declared. A name
    read again after the load is in effect from a file, so it cannot be listed as read
    before it; every read-again name is read after the load, by the start or a request."""
    # None of the listed names is set, so only an explicit read of one is seen: code that
    # walks the environment (dict(os.environ), the loader itself) reads every key present.
    listed = ep.READ_BEFORE_LOAD | ep.READ_AGAIN_AFTER_LOAD | {"JARVIS_USER_HOME"}
    env = {key: value for key, value in os.environ.items() if key not in listed}
    env.update({"JARVIS_HOME": str(tmp_path / "data"), "PYTHONDONTWRITEBYTECODE": "1"})
    out = subprocess.run([sys.executable, "-c", _AFTER_SPY], cwd=ROOT, env=env, capture_output=True,
                         text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    after = set(json.loads(out.stdout.rsplit("SPY", 1)[1])["after"])
    assert ep.READ_AGAIN_AFTER_LOAD - {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SPOTIFY_CLIENT_ID",
                                       "SPOTIFY_CLIENT_SECRET"} <= after
    assert {"GOOGLE_CLIENT_ID", "SPOTIFY_CLIENT_ID"} <= after      # the plugin manager's init, after the load
    read_again = (ep.READ_BEFORE_LOAD - ep.FROM_PROCESS_ONLY) & after
    assert not read_again, f"{sorted(read_again)} are read after the load: a .env value is in effect"


@pytest.mark.parametrize("line, shown", [
    ("MixedCase=a-real-value", False),       # D35: one case only
    ("KEYONLY", False),                       # D36: no value is not a real value
    ("lower_plain=x", True),
])
def test_an_undeclared_name_is_printed_only_when_it_is_plain(tmp_path, line, shown):
    from scripts import doctor

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text(line + "\n", encoding="utf-8")
    key = line.split("=", 1)[0]
    check = doctor.check_config_sources(root, {})
    assert (key in [row["key"] for row in check.data["sources"]]) is shown


def test_the_data_homes_values_decide_its_names_and_the_repo_wins(tmp_path):
    """D28/D29: a plain name only in the data home is shown; where both files have it, the
    repo's value (padding only) is the one the hub keeps, so the name is withheld."""
    from scripts import doctor

    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    (root / ".env").write_text("SEEDLINE===\n", encoding="utf-8")
    (home / ".env").write_text("HOME_PLAIN=on\nSEEDLINE=a-real-value\n", encoding="utf-8")
    check = doctor.check_config_sources(root, {"JARVIS_USER_HOME": str(home)})
    shown = [row["key"] for row in check.data["sources"]]
    assert "HOME_PLAIN" in shown and "SEEDLINE" not in shown


def test_a_commented_declaration_in_env_example_is_a_declaration():
    """D23: .env.example declares a knob it leaves commented out."""
    from scripts import doctor

    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    commented = re.findall(r"^#[ \t]*([A-Z][A-Z0-9_]+)=", text, re.M)
    assert commented and set(commented) <= doctor.declared_env_names(ROOT)


def test_a_403_is_asked_again_with_the_admin_token(tmp_path):
    """D09: a hub that answers 403 without a credential gets the admin token (on this
    machine), as it does after a 401."""
    from scripts import doctor

    payload = {"sources": [{"key": "JARVIS_MODEL", "layer": "repo_env", "shadowed": []}], "files": {}}
    opener = _sources_hub(payload, refuse=403)
    env = {"NERVA_HUB_URL": "http://127.0.0.1:8080", "JARVIS_ADMIN_TOKEN": "adm-403"}
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=doctor.check_readyz(opener, env=env))
    assert check.detail.startswith("read from the running hub")


def test_a_stored_posture_that_is_not_json_is_off_for_another_categorys_listing(tmp_path, monkeypatch):
    """S04: a posture row written around the API as text that is not JSON is read as
    off, so listing any other category still works."""
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db()
    conn = settings_db.get_conn()
    conn.execute("UPDATE settings SET value=? WHERE category='product' AND key='posture'", ("not json {",))
    conn.commit()
    conn.close()
    assert settings_db.get_category("llm")


def test_a_third_load_keeps_the_attribution_the_first_made(tmp_path, monkeypatch):
    """E09: every load keeps a key's file layer while the environment holds the value
    the file set."""
    repo = tmp_path / ".env"
    repo.write_text("PROV_THIRD_KEY=same\n", encoding="utf-8")
    monkeypatch.delenv("PROV_THIRD_KEY", raising=False)
    try:
        for _ in range(3):
            table = ep.load_layered_env(repo, None)
            assert table["PROV_THIRD_KEY"]["layer"] == ep.REPO_ENV
    finally:
        os.environ.pop("PROV_THIRD_KEY", None)


def test_a_data_home_that_is_the_repo_env_is_named_so_even_when_loading_is_off(tmp_path, monkeypatch):
    """E21: the same file is reported as such before the switch is consulted."""
    repo = tmp_path / ".env"
    repo.write_text("PYTHON_DOTENV_DISABLED=1\n", encoding="utf-8")
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    try:
        ep.load_layered_env(repo, repo)
        assert ep.files()["user_env"]["kind"] == "same file as the repo .env"
    finally:
        os.environ.pop("PYTHON_DOTENV_DISABLED", None)


# ── the nits ───────────────────────────────────────────────────────────────────

def test_the_prediction_resolves_a_rebound_key_in_file_order(tmp_path, monkeypatch):
    """n1: the hub loads XA='pq' from this file; the prediction read the dict, which keeps
    a rebound key at its first place with its last value, and said ''."""
    repo = tmp_path / ".env"
    repo.write_text("XA=\nXA=p${XA}q\nXA='${XA}'\n", encoding="utf-8")
    monkeypatch.delenv("XA", raising=False)
    predicted = ep.after_repo_layer(repo, {})
    try:
        ep.load_layered_env(repo, None)
        assert predicted["XA"] == os.environ["XA"] == "pq"
    finally:
        os.environ.pop("XA", None)


def test_the_prediction_follows_a_data_home_named_through_a_rebound_variable(tmp_path):
    from scripts import doctor

    base_a, base_b = tmp_path / "a", tmp_path / "b"
    for base in (base_a, base_b):
        (base / "h").mkdir(parents=True)
    (base_a / "h" / ".env").write_text("FROM_A=1\n", encoding="utf-8")
    (base_b / "h" / ".env").write_text("FROM_B=1\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text(f"BASE={base_a}\nJARVIS_USER_HOME=${{BASE}}/h\nBASE={base_b}\n", encoding="utf-8")
    check = doctor.check_config_sources(root, {})
    keys = [row["key"] for row in check.data["sources"]]
    assert "FROM_A" in keys and "FROM_B" not in keys


def test_the_hub_load_logs_a_parse_warning_once(tmp_path, monkeypatch, caplog):
    """n3: the load parsed each file twice, so every python-dotenv warning came twice."""
    import logging

    repo = tmp_path / ".env"
    repo.write_text("GOOD_ONE=1\nthis line is not a binding\n", encoding="utf-8")
    monkeypatch.delenv("GOOD_ONE", raising=False)
    try:
        with caplog.at_level(logging.WARNING, logger="dotenv.main"):
            ep.load_layered_env(repo, None)
        assert len([r for r in caplog.records if "could not parse" in r.getMessage()]) == 1
    finally:
        os.environ.pop("GOOD_ONE", None)


def test_a_rewrite_that_keeps_size_and_mtime_is_parsed_again(tmp_path):
    """n4: the cache key held only the mtime and the size."""
    path = tmp_path / ".env"
    path.write_text("AAA=1\n", encoding="utf-8")
    stat = path.stat()
    assert ep.env_file_keys(path) == ["AAA"]
    path.write_text("BBB=2\n", encoding="utf-8")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert ep.env_file_keys(path) == ["BBB"]


# ── n9: the nerva CLI's client keeps its tokens on the configured hub ────────────

class _Recorder:
    """A loopback HTTP server that records each request and answers from ``respond``."""

    def __init__(self, respond):
        import http.server
        import threading

        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                status, body, headers = respond(self.path)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def recorders():
    made = []

    def make(respond):
        server = _Recorder(respond)
        made.append(server)
        return server

    yield make
    for server in made:
        server.close()


def test_the_cli_client_does_not_carry_its_tokens_through_a_redirect(recorders):
    from agents.cli.client import HubClient, HubError

    elsewhere = recorders(lambda path: (200, b"{}", {"Content-Type": "application/json"}))
    hub = recorders(lambda path: (302, b"", {"Location": f"{elsewhere.url}/collect"}))
    client = HubClient(hub.url, admin_token="adm-n9", user_token="usr-n9")
    with pytest.raises(HubError) as refused:
        client.get("/api/status")
    assert refused.value.status == 302 and elsewhere.requests == []


def test_the_cli_client_never_goes_through_a_proxy_to_this_machine(recorders, monkeypatch):
    from agents.cli.client import HubClient

    proxy = recorders(lambda path: (200, b'{"from": "the proxy"}', {"Content-Type": "application/json"}))
    hub = recorders(lambda path: (200, b'{"from": "the hub"}', {"Content-Type": "application/json"}))
    import urllib.request

    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("http_proxy", proxy.url)
    monkeypatch.setenv("HTTP_PROXY", proxy.url)
    monkeypatch.setattr(urllib.request, "_opener", None)     # urllib's own opener reads the proxy anew
    assert HubClient(hub.url, admin_token="adm-n9").get("/api/status") == {"from": "the hub"}
    assert proxy.requests == [] and hub.requests[0][1]["x-admin-token"] == "adm-n9"


def test_a_cli_hub_address_that_is_not_http_is_refused_not_read(tmp_path):
    """A file: hub address used to be opened: a local file answered as the hub."""
    from agents.cli.client import HubClient, HubUnavailable

    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "status").write_text('{"ok": true}', encoding="utf-8")
    with pytest.raises(HubUnavailable):
        HubClient(f"file://{tmp_path}").get("/api/status")
