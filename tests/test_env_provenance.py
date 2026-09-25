"""H273 — every effective configuration key says where it came from.

Configuration reaches the hub in three layers, the first one wins (python-dotenv's
override=False): the process environment (the shell, a systemd EnvironmentFile,
docker -e), the repo .env of a development checkout, and the data-home .env of a
packaged install. PluginManager.build used to load both files with two load_dotenv
calls and remember nothing about which layer supplied a key, so "why is Nerva using
the cloud model?" had no one-screen answer. Hermes' own notes ask for exactly this
table and do not have it.

The table names keys and layers only, never a value: the admin route masks at the
same boundary as GET /api/admin/env, and the doctor prints names.
"""
from __future__ import annotations

import io
import json
import logging
import os
import random
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
from agents.core import env_provenance as ep  # noqa: E402

SECRET_VALUE = "sk-provenance-test-value-7f3a"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def layers(tmp_path, monkeypatch):
    """A repo .env and a data-home .env; the keys under test start unset."""
    repo = _write(tmp_path / "repo" / ".env",
                  f"PROV_REPO_ONLY=1\nPROV_BOTH=from-repo\nexport PROV_SHELL=from-repo\nPROV_API_KEY={SECRET_VALUE}\n")
    home = _write(tmp_path / "home" / ".env",
                  "PROV_HOME_ONLY=1\nPROV_BOTH=from-home\nPROV_SHELL=from-home\n")
    for key in ("PROV_REPO_ONLY", "PROV_BOTH", "PROV_HOME_ONLY", "PROV_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PROV_SHELL", "from-shell")
    yield repo, home
    for key in ("PROV_REPO_ONLY", "PROV_BOTH", "PROV_HOME_ONLY", "PROV_API_KEY"):
        os.environ.pop(key, None)


def test_each_key_reports_the_layer_that_won(layers):
    repo, home = layers
    table = ep.load_layered_env(repo, home)
    assert table["PROV_HOME_ONLY"] == {"layer": "user_env", "shadowed": []}
    assert table["PROV_REPO_ONLY"] == {"layer": "repo_env", "shadowed": []}
    assert table["PROV_BOTH"] == {"layer": "repo_env", "shadowed": ["user_env"]}
    assert table["PROV_SHELL"] == {"layer": "process", "shadowed": ["repo_env", "user_env"]}
    # the load itself is unchanged: first layer wins, nothing is overwritten
    assert os.environ["PROV_BOTH"] == "from-repo" and os.environ["PROV_SHELL"] == "from-shell"
    assert os.environ["PROV_HOME_ONLY"] == "1"


def test_the_table_never_holds_a_value(layers):
    repo, home = layers
    table = ep.load_layered_env(repo, home)
    blob = json.dumps(ep.provenance())
    assert SECRET_VALUE not in blob and "from-repo" not in blob and "from-shell" not in blob
    assert table["PROV_API_KEY"]["layer"] == "repo_env"


def test_a_key_set_after_the_load_is_reported_as_runtime(layers, monkeypatch):
    repo, home = layers
    ep.load_layered_env(repo, home)
    monkeypatch.setenv("PROV_LATE", "x")
    assert ep.provenance()["PROV_LATE"] == {"layer": "runtime", "shadowed": []}


def test_a_missing_file_is_simply_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("PROV_SHELL", "x")
    table = ep.load_layered_env(tmp_path / "no.env", None)
    assert table["PROV_SHELL"] == {"layer": "process", "shadowed": []}


_GRAMMAR = [
    "\ufeffBOM_KEY=1\nB2=2\n",                            # a UTF-8 BOM (Notepad, PowerShell 5)
    'W="C:\\\\models\\\\"\nX="y"\nZ=1\n',              # a quoted path ending in an escaped backslash
    "P='C:\\\\'\nQ='y'\nR=2\n",
    "A=1\nA\n",                                          # the last binding has no "=": nothing is set
    "G\nX=1\nG=2\n",                                     # dotenv's order is first-seen
    "A=1\rB=2\r",
    "A=1\n# B=2\n\nC = 3\n",
    "export D=1\n  E=2 # comment\n",
    "'F'=1\nG\nH=\n",                                   # G has no "=": dotenv never sets it
    'I="line one\nJ=not a key\nline three"\nK=2\n',       # nothing inside a quoted value is a key
    "L='it''s\nM=still inside'\nN=3\n",                  # junk after the quote: L is skipped, M parsed
    'O="escaped \\" quote\nP=inside"\nQ=1\n',
    "R=unquoted 'not a quote\nS=1\n",
    "T='single\nU=inside'\nV=1\n",
    'W="a" trailing\nX=1\n',
    "AA='unclosed\nBB=2\n",
    'CC="x"\r\nDD=1\r\n',
    "EE='a\\'b'\nFF=1\n",
    "  \n\n  GG=1",
    "HH =  'a' junk # c\nII=1",
    "JJ=a # c\n'K K'=2\n",
    'LL = "multi\nline" # c\nMM=1\n',
    "export=1\n",
    "#only\n",
    "",
]


def _dotenv_keys(text):
    from dotenv import dotenv_values

    return [key for key, value in dotenv_values(stream=io.StringIO(text)).items() if value is not None]


@pytest.mark.parametrize("text", _GRAMMAR)
def test_the_stdlib_port_parses_keys_exactly_as_python_dotenv_1_2_3_does(text, caplog):
    caplog.set_level(logging.CRITICAL, logger="dotenv.main")
    assert ep._port_keys(text) == _dotenv_keys(text)


def test_the_stdlib_port_matches_python_dotenv_on_random_files(caplog):
    """A seeded differential fuzz over the characters the grammar turns on."""
    caplog.set_level(logging.CRITICAL, logger="dotenv.main")
    atoms = ["A", "B", "K1", "=", "'", '"', "\\", "\\\\", "\n", "\r\n", "\r", " ", "\t", "#", "export ", "x",
             "\\'", '\\"', "\ufeff"]
    rng = random.Random(273)
    for _ in range(4000):
        text = "".join(rng.choice(atoms) for _ in range(rng.randint(1, 16)))
        assert ep._port_keys(text) == _dotenv_keys(text), repr(text)


def test_the_port_reads_no_key_inside_a_value():
    text = 'I="line one\nJ=not a key\nline three"\nL=\'it\'\'s\nM=still inside\'\nN=3\n'
    assert ep._port_keys(text) == ["I", "M", "N"]


def test_file_keys_come_from_python_dotenv_when_it_is_there(tmp_path):
    path = _write(tmp_path / ".env", "\ufeffOPENAI_API_KEY=1\nA=1\nA\n")
    assert ep.env_file_keys(path) == ["OPENAI_API_KEY"] == _dotenv_keys(path.read_text(encoding="utf-8"))


def test_the_port_is_the_fallback_without_python_dotenv(monkeypatch):
    monkeypatch.setitem(sys.modules, "dotenv", None)        # a broken install
    assert ep.text_keys("\ufeffK=1\nL\n") == ["K"]


def test_derive_matches_the_load_without_touching_the_environment(layers):
    repo, home = layers
    environ = {"PROV_SHELL": "from-shell"}
    derived = ep.derive(repo, home, environ)
    assert environ == {"PROV_SHELL": "from-shell"}                   # nothing was loaded
    assert "PROV_HOME_ONLY" not in os.environ
    loaded = ep.load_layered_env(repo, home)
    for key in ("PROV_REPO_ONLY", "PROV_BOTH", "PROV_HOME_ONLY", "PROV_SHELL", "PROV_API_KEY"):
        assert derived[key] == loaded[key], key


def test_the_plugin_manager_loads_through_the_provenance_table(monkeypatch, tmp_path):
    """PluginManager.build no longer calls load_dotenv itself: it asks for the hub's one
    load, which resolves the data home after the repo layer is loaded, so a
    JARVIS_USER_HOME set in the repo .env names it."""
    import agents.core.plugin_manager as pm

    seen = []
    named_by_the_repo_env = tmp_path / "named"

    def load(repo, home):
        os.environ["JARVIS_USER_HOME"] = str(named_by_the_repo_env)   # as the repo .env would
        seen.append((repo, home() if callable(home) else home))
        return {}

    monkeypatch.setattr(ep, "load_layered_env", load)
    monkeypatch.setattr(ep, "_HUB_LOADED", None)
    monkeypatch.setenv("JARVIS_USER_HOME", str(tmp_path))
    _write(tmp_path / ".env", "PROV_HOME_ONLY=1\n")

    class _Stop(Exception):
        pass

    monkeypatch.setattr(pm, "CloudLLMPlugin", lambda **_: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        pm.PluginManager().build(object())
    assert seen == [(ROOT / ".env", named_by_the_repo_env / ".env")]
    assert "load_dotenv(" not in Path(pm.__file__).read_text(encoding="utf-8").split("def build", 1)[1]


# ── the admin route ────────────────────────────────────────────────────────────

@pytest.fixture
def admin(monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "prov-admin")
    with TestClient(web.app) as client:
        yield client


def test_the_sources_route_is_admin_only(admin):
    assert admin.get("/api/admin/env/sources").status_code in (401, 403)


def test_the_sources_route_names_layers_and_never_values(admin, layers):
    repo, home = layers
    ep.load_layered_env(repo, home)
    reply = admin.get("/api/admin/env/sources", headers={"X-Admin-Token": "prov-admin"})
    assert reply.status_code == 200 and "no-store" in reply.headers["cache-control"]
    rows = {row["key"]: row for row in reply.json()["sources"]}
    assert rows["PROV_BOTH"] == {"key": "PROV_BOTH", "layer": "repo_env", "label": "repo .env",
                                 "shadowed": ["user_env"], "masked": False}
    assert rows["PROV_API_KEY"]["masked"] is True                      # /api/admin/env masks it
    assert rows["PROV_SHELL"]["layer"] == "process"
    assert SECRET_VALUE not in reply.text and "from-repo" not in reply.text
    assert set(reply.json()["files"]) == {"repo_env", "user_env"}


# ── the doctor ────────────────────────────────────────────────────────────────

def test_the_doctor_names_each_configuration_keys_layer(tmp_path, monkeypatch):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", f"JARVIS_PORT=8081\nJARVIS_RATE_LIMIT=5\nOPENAI_API_KEY={SECRET_VALUE}\n")
    home = tmp_path / "home"
    _write(home / ".env", "JARVIS_PORT=9000\nTELEGRAM_BOT_TOKEN=tg-home-value-51c9\n")
    env = {"JARVIS_USER_HOME": str(home), "OPENAI_API_KEY": "from-shell", "PATH": "/usr/bin"}
    check = doctor.check_config_sources(root, env)
    assert check.status == doctor.OK
    rows = {row["key"]: row for row in check.data["sources"]}
    assert rows["JARVIS_PORT"] == {"key": "JARVIS_PORT", "layer": "repo_env", "shadowed": ["user_env"]}
    assert rows["JARVIS_RATE_LIMIT"]["note"] == ep.BEFORE_LOAD_NOTE   # importing the hub freezes it
    assert rows["OPENAI_API_KEY"] == {"key": "OPENAI_API_KEY", "layer": "process",
                                      "shadowed": ["repo_env"]}
    assert rows["TELEGRAM_BOT_TOKEN"]["layer"] == "user_env"              # the data-home layer is read
    assert "PATH" not in rows                                          # not configuration
    assert "1 key set in the process environment overrides a .env value" in check.reason
    assert f"repo .env {root / '.env'} (present)" in check.detail
    assert f"data-home .env {home / '.env'} (present)" in check.detail
    assert "not configured" in doctor.check_config_sources(root, {}).detail
    assert check.detail.startswith("predicted from this shell's environment")
    text = doctor.format_report(doctor.DoctorReport(ok=True, root=str(root), checks=[check]))
    assert "OPENAI_API_KEY" in text and "process environment" in text
    assert "(ignored: repo .env)" in text and "reads it before the .env files are loaded" in text
    assert SECRET_VALUE not in text and "from-shell" not in text and "tg-home-value-51c9" not in text
    assert SECRET_VALUE not in json.dumps(doctor.DoctorReport(ok=True, root=str(root), checks=[check]).to_dict())


def test_the_doctor_runs_the_config_check_in_its_advisory_set():
    from scripts import doctor

    assert "config_sources" in doctor.ADVISORY and "config_sources" not in doctor.REQUIRED


# ── the settings plane ────────────────────────────────────────────────────────

def test_settings_rows_say_default_or_set(tmp_path, monkeypatch):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db()
    settings_db.put_category("memory", {"recall_top_k": 9})
    rows = {row["key"]: row for row in settings_db.get_category("memory")}
    assert rows["recall_top_k"]["source"] == "set"
    assert rows["recall_enabled"]["source"] == "default"
    everything = settings_db.get_all()
    assert all(row["source"] in ("default", "set", "undeclared") for rows in everything.values() for row in rows)


def test_nerva_config_list_shows_each_values_source(tmp_path, monkeypatch):
    from agents.core import settings_db
    from tests.test_nerva_cli import _run

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db()
    settings_db.put_category("memory", {"recall_top_k": 9})
    code, out, _err, _hub = _run(["config", "list", "memory"])
    assert code == 0
    assert "memory.recall_top_k = 9  (number, set)" in out
    assert "memory.recall_enabled = false  (toggle, default)" in out
    code, out, _err, _hub = _run(["config", "list", "memory", "--json"])
    rows = {row["key"]: row for row in json.loads(out)["memory"]}
    assert rows["recall_top_k"]["source"] == "set"


# ── review round: a named pipe, the data home, reloads, the doctor's reach ─────

@pytest.fixture
def scrub():
    """Keys a test loads straight into os.environ, removed afterwards."""
    keys = []
    yield keys
    for key in keys:
        os.environ.pop(key, None)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_a_named_pipe_env_is_read_once_and_loaded(tmp_path, scrub):
    fifo = tmp_path / ".env"
    os.mkfifo(fifo)
    scrub.append("FIFO_OPENAI_API_KEY")
    os.environ.pop("FIFO_OPENAI_API_KEY", None)

    def writer():
        with open(fifo, "w", encoding="utf-8") as stream:
            stream.write("FIFO_OPENAI_API_KEY=sk-fifo\n")

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    table = ep.load_layered_env(fifo, None)
    thread.join(5)
    assert os.environ["FIFO_OPENAI_API_KEY"] == "sk-fifo"
    assert table["FIFO_OPENAI_API_KEY"] == {"layer": "repo_env", "shadowed": []}
    assert ep.files()["repo_env"] == {"path": str(fifo), "kind": "fifo", "present": True, "read": True}


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_the_doctor_never_opens_a_named_pipe(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    root.mkdir()
    os.mkfifo(root / ".env")                                  # no writer: opening it would block
    result = {}
    thread = threading.Thread(target=lambda: result.update(check=doctor.check_config_sources(root, {})),
                              daemon=True)
    thread.start()
    thread.join(20)
    assert "check" in result, "the doctor blocked on a named pipe"
    assert "a named pipe: the hub reads it, the doctor does not" in result["check"].detail


def test_a_data_home_named_in_the_repo_env_is_loaded(tmp_path, monkeypatch, scrub):
    from agents.core.paths import user_home

    home = tmp_path / "home"
    _write(home / ".env", "PROV_NAMED_HOME_KEY=1\n")
    repo = _write(tmp_path / "repo" / ".env", f"JARVIS_USER_HOME={home}\n")
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    scrub.extend(["JARVIS_USER_HOME", "PROV_NAMED_HOME_KEY"])
    table = ep.load_layered_env(repo, lambda: (user_home() / ".env") if user_home() is not None else None)
    assert os.environ["PROV_NAMED_HOME_KEY"] == "1"
    assert table["PROV_NAMED_HOME_KEY"]["layer"] == "user_env"
    assert ep.files()["user_env"] == {"path": str(home / ".env"), "kind": "file", "present": True, "read": True}
    derived = ep.derive(repo, lambda merged: Path(merged["JARVIS_USER_HOME"]) / ".env"
                        if merged.get("JARVIS_USER_HOME") else None, {})
    assert derived["PROV_NAMED_HOME_KEY"]["layer"] == "user_env"          # the doctor follows it too


def test_a_second_load_keeps_what_the_first_load_attributed(layers):
    repo, home = layers
    ep.load_layered_env(repo, home)
    table = ep.load_layered_env(repo, home)
    assert table["PROV_REPO_ONLY"] == {"layer": "repo_env", "shadowed": []}
    assert table["PROV_HOME_ONLY"] == {"layer": "user_env", "shadowed": []}
    assert table["PROV_BOTH"] == {"layer": "repo_env", "shadowed": ["user_env"]}
    assert table["PROV_SHELL"] == {"layer": "process", "shadowed": ["repo_env", "user_env"]}


def test_a_bare_key_in_a_file_overrides_nothing(tmp_path, monkeypatch):
    """A key written without "=" sets nothing (python-dotenv skips it), so the file
    does not define a value the shell's would override."""
    repo = _write(tmp_path / ".env", "PROV_BARE\n")
    monkeypatch.setenv("PROV_BARE", "shell")
    table = ep.load_layered_env(repo, None)
    assert table["PROV_BARE"] == {"layer": "process", "shadowed": []}
    assert ep.derive(repo, None, {"PROV_BARE": "shell"})["PROV_BARE"] == {"layer": "process", "shadowed": []}


def test_the_same_file_twice_is_one_layer(tmp_path, scrub):
    repo = _write(tmp_path / ".env", "PROV_SAME=1\n")
    scrub.append("PROV_SAME")
    os.environ.pop("PROV_SAME", None)
    table = ep.load_layered_env(repo, tmp_path / "." / ".env")
    assert table["PROV_SAME"] == {"layer": "repo_env", "shadowed": []}
    assert ep.files()["user_env"]["kind"] == "same file as the repo .env"
    assert ep.derive(repo, tmp_path / ".env", {})["PROV_SAME"] == {"layer": "repo_env", "shadowed": []}


def test_python_dotenv_disabled_loads_nothing_and_derive_agrees(tmp_path, monkeypatch, scrub):
    repo = _write(tmp_path / ".env", "PROV_DISABLED=1\n")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "yes")
    scrub.append("PROV_DISABLED")
    os.environ.pop("PROV_DISABLED", None)
    table = ep.load_layered_env(repo, None)
    assert "PROV_DISABLED" not in os.environ and "PROV_DISABLED" not in table
    assert "PROV_DISABLED" not in ep.derive(repo, None, {"PYTHON_DOTENV_DISABLED": "True"})
    assert "PROV_DISABLED" in ep.derive(repo, None, {"PYTHON_DOTENV_DISABLED": "0"})


def test_the_route_flags_a_key_the_import_reads_first_and_names_the_files_read(admin, tmp_path, monkeypatch,
                                                                                scrub):
    repo = _write(tmp_path / ".env", "JARVIS_RATE_LIMIT=9123\nPROV_ROUTE_KEY=1\n")
    monkeypatch.delenv("JARVIS_RATE_LIMIT", raising=False)
    scrub.extend(["JARVIS_RATE_LIMIT", "PROV_ROUTE_KEY"])
    os.environ.pop("PROV_ROUTE_KEY", None)
    monkeypatch.setenv("_PROV_PRIVATE", "1")
    ep.load_layered_env(repo, tmp_path / "missing-home" / ".env")
    reply = admin.get("/api/admin/env/sources", headers={"X-Admin-Token": "prov-admin"}).json()
    rows = {row["key"]: row for row in reply["sources"]}
    assert rows["JARVIS_RATE_LIMIT"]["note"] == ep.BEFORE_LOAD_NOTE
    assert "note" not in rows["PROV_ROUTE_KEY"]
    assert "_PROV_PRIVATE" not in rows
    assert reply["files"]["repo_env"] == {"path": str(repo), "present": True, "kind": "file", "read": True}
    assert reply["files"]["user_env"] == {"path": str(tmp_path / "missing-home" / ".env"), "present": False,
                                          "kind": "absent", "read": False}


# ── the doctor, after review ───────────────────────────────────────────────────

UNQUOTED_PEM = (
    "GOOGLE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\n"
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\n"
    "k8sA7QxLmNpQ2vR9tW3yUeHbFgJdKcS1aO5iX0zN4oP6qT8rY==\n"
    "-----END PRIVATE KEY-----\n"
    "OPENAI_API_KEY=sk-after-the-pem\n"
)


def test_the_doctor_never_prints_value_material_as_a_name(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", UNQUOTED_PEM)
    check = doctor.check_config_sources(root, {})
    report = doctor.DoctorReport(ok=True, root=str(root), checks=[check])
    text, blob = doctor.format_report(report), json.dumps(report.to_dict())
    assert "k8sA7QxLmNp" in "".join(ep.env_file_keys(root / ".env"))        # dotenv really makes it a key
    assert "k8sA7QxLmNp" not in text and "k8sA7QxLmNp" not in blob
    assert check.status == doctor.WARN and check.reason.startswith("withheld_env_names:1")
    assert {row["key"] for row in check.data["sources"]} >= {"GOOGLE_PRIVATE_KEY", "OPENAI_API_KEY"}


def test_the_doctor_shows_every_env_file_key_and_what_the_hub_reads_but_not_other_tools(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", "MY_OWN_SETTING=1\n")
    env = {"DEV_MODE": "1", "TELEGRAM_ALLOWED_USER_IDS": "42", "GH_TOKEN": "x", "CLOUDSDK_AUTH_ACCESS_TOKEN": "y",
           "PATH": "/usr/bin", "TZ": "UTC"}
    rows = {row["key"] for row in doctor.check_config_sources(root, env).data["sources"]}
    assert {"MY_OWN_SETTING", "DEV_MODE", "TELEGRAM_ALLOWED_USER_IDS"} <= rows
    assert not rows & {"GH_TOKEN", "CLOUDSDK_AUTH_ACCESS_TOKEN", "PATH", "TZ"}


def test_the_doctor_survives_data_homes_it_cannot_resolve(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", "A=1\n")
    for home in ("~nosuchuser_h273/x", "/" + "x" * 300 + "/y", "\x00bad"):
        check = doctor.check_config_sources(root, {"JARVIS_USER_HOME": home})
        assert check.name == "config_sources" and check.status in (doctor.OK, doctor.WARN)


def test_the_doctor_reports_an_unimportable_provenance_module(tmp_path, monkeypatch):
    import agents.core
    from scripts import doctor

    monkeypatch.delattr(agents.core, "env_provenance", raising=False)   # a broken install: no module
    monkeypatch.setitem(sys.modules, "agents.core.env_provenance", None)
    check = doctor.check_config_sources(tmp_path, {})
    assert check.status == doctor.WARN and check.reason == "provenance_unavailable"


def _hub(sources=None, status=200, seen=None, token=None):
    import urllib.error

    class _Resp:
        def __init__(self, body):
            self.body, self.status = body, 200

        def read(self):
            return self.body

        def close(self):
            pass

    def opener(request, timeout=None):
        url = getattr(request, "full_url", request)
        if seen is not None:
            seen.append((url, dict(getattr(request, "headers", {}) or {})))
        if url.endswith("/readyz"):
            return _Resp(b"ok")
        if url.endswith("/api/admin/env/sources"):
            sent = {k.lower(): v for k, v in dict(getattr(request, "headers", {}) or {}).items()}
            if token is not None and sent.get("x-admin-token") != token:
                raise urllib.error.HTTPError(url, 401, "admin token required", {}, None)
            if status != 200:
                raise urllib.error.HTTPError(url, status, "refused", {}, None)
            return _Resp(json.dumps(sources).encode("utf-8"))
        raise urllib.error.URLError("nothing here")
    return opener


def test_the_doctor_reads_the_running_hubs_own_table(tmp_path):
    from scripts import doctor

    seen = []
    payload = {"sources": [
        {"key": "OPENAI_API_KEY", "layer": "process", "shadowed": ["repo_env"], "label": "process environment"},
        {"key": "JARVIS_MODEL", "layer": "user_env", "shadowed": [], "label": "data-home .env"},
        {"key": "JARVIS_RATE_LIMIT", "layer": "repo_env", "shadowed": [], "label": "repo .env"},
        {"key": "JARVIS_HOST", "layer": "process", "shadowed": [], "label": "process environment"},
    ], "files": {"repo_env": {"path": "/srv/nerva/.env", "present": True, "kind": "file", "read": True}}}
    opener = _hub(payload, seen=seen, token="adm-7c1")
    env = {"JARVIS_ADMIN_TOKEN": "adm-7c1"}
    readyz = doctor.check_readyz(opener, env=env)
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=readyz)
    rows = {row["key"]: row for row in check.data["sources"]}
    assert rows["JARVIS_MODEL"]["layer"] == "user_env"          # the shell does not have it; the hub does
    assert rows["OPENAI_API_KEY"]["shadowed"] == ["repo_env"]
    assert rows["JARVIS_RATE_LIMIT"]["note"] == ep.BEFORE_LOAD_NOTE
    assert "note" not in rows["JARVIS_HOST"]                         # from the process: it is in effect
    assert check.detail.startswith("read from the running hub at http://127.0.0.1:8080")
    assert "/srv/nerva/.env (file)" in check.detail
    sent = [{k.lower(): v for k, v in headers.items()} for url, headers in seen
            if url.endswith("/api/admin/env/sources")]
    # asked without the credential first (a hub in dev posture answers), then with it
    assert [h.get("x-admin-token") for h in sent] == [None, "adm-7c1"]


def test_the_doctor_predicts_when_the_hub_refuses_or_is_down(tmp_path):
    from scripts import doctor

    _write(tmp_path / ".env", "PROV_LOCAL=1\n")
    opener = _hub(status=401)
    refused = doctor.check_config_sources(tmp_path, {}, opener=opener, readyz=doctor.check_readyz(opener, env={}))
    assert refused.detail.startswith("predicted from this shell's environment")
    assert {row["key"] for row in refused.data["sources"]} == {"PROV_LOCAL"}
    answering = _hub({"sources": [{"key": "PROV_FROM_HUB", "layer": "repo_env", "shadowed": []}], "files": {}})
    down = doctor.Check("readyz", doctor.WARN, "server_not_running")
    check = doctor.check_config_sources(tmp_path, {}, opener=answering, readyz=down)
    assert check.detail.startswith("predicted")                      # a hub that is not ready is not asked
    assert {row["key"] for row in check.data["sources"]} == {"PROV_LOCAL"}


def test_a_failure_inside_the_config_check_is_a_named_reason(tmp_path, monkeypatch):
    from scripts import doctor

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(ep, "derive", boom)
    check = doctor.check_config_sources(tmp_path, {})
    assert check.status == doctor.WARN and check.reason == "provenance_unavailable:RuntimeError"



def test_the_doctor_names_a_env_file_python_dotenv_cannot_read(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_bytes("OPENAI_API_KEY=café\n".encode("latin-1"))
    check = doctor.check_config_sources(root, {})
    assert check.status == doctor.WARN and check.reason.startswith("env_not_utf8:repo_env")
    assert "not UTF-8" in check.detail


# ── the settings plane, after review ───────────────────────────────────────────

@pytest.fixture
def settings(tmp_path, monkeypatch):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db()
    return settings_db


def test_a_stored_key_nothing_declares_is_undeclared(settings):
    conn = settings.get_conn()
    conn.execute("INSERT INTO settings(category, key, value, label, kind, opts) "
                 "VALUES ('memory', 'retired_knob', '1', '', 'number', '[]')")
    conn.commit()
    conn.close()
    rows = {row["key"]: row for row in settings.get_category("memory")}
    assert rows["retired_knob"]["source"] == "undeclared"
    assert settings.get_all()["memory"][[r["key"] for r in settings.get_all()["memory"]].index("retired_knob")]["source"] == "undeclared"


def test_a_value_a_product_posture_forces_is_named_beside_the_stored_one(settings):
    rows = {row["key"]: row for row in settings.get_category("memory")}
    assert "overlay" not in rows["recall_enabled"]                      # posture off: nothing forced
    settings.put_category("product", {"posture": "companion_wave1"})
    rows = {row["key"]: row for row in settings.get_category("memory")}
    row = rows["recall_enabled"]
    assert row["value"] is False and row["source"] == "default"        # the stored row, as before
    assert row["in_effect"] is True and row["overlay"] == "product.posture:companion_wave1"
    assert "overlay" not in rows["recall_top_k"]
    everything = {row["key"]: row for row in settings.get_all()["memory"]}
    assert everything["recall_enabled"]["overlay"] == "product.posture:companion_wave1"


def test_a_secret_whose_key_is_lost_is_unreadable_not_default(settings, monkeypatch):
    class _LostKey:
        def encrypt_value(self, value):
            return "ciphertext"

        def decrypt_value(self, value):
            raise ValueError("the key is gone")

    monkeypatch.setattr(settings, "_field_cipher", _LostKey())
    settings.put_category("plugins", {"twilio_auth_token": "AC-secret"})
    rows = {row["key"]: row for row in settings.get_category("plugins")}
    assert rows["twilio_auth_token"]["value"] == ""
    assert rows["twilio_auth_token"]["source"] == "unreadable"
    assert rows["notion_integration_token"]["source"] == "default"      # never set: still the default


def test_nerva_config_list_says_what_a_posture_puts_in_effect(settings):
    from tests.test_nerva_cli import _run

    settings.put_category("product", {"posture": "companion_wave1"})
    code, out, _err, _hub = _run(["config", "list", "memory"])
    assert code == 0
    assert "memory.recall_enabled = false  (toggle, default; in effect: true by product.posture:companion_wave1)" in out
