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

import json
import os
import sys
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


@pytest.mark.parametrize("text", _GRAMMAR)
def test_env_file_keys_parses_keys_exactly_as_python_dotenv_does(tmp_path, text):
    import io

    from dotenv import dotenv_values

    expected = [key for key, value in dotenv_values(stream=io.StringIO(text)).items() if value is not None]
    assert ep.env_file_keys(_write(tmp_path / ".env", text)) == expected


def test_env_file_keys_reads_no_key_inside_a_value(tmp_path):
    text = 'I="line one\nJ=not a key\nline three"\nL=\'it\'\'s\nM=still inside\'\nN=3\n'
    assert ep.env_file_keys(_write(tmp_path / ".env", text)) == ["I", "M", "N"]


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
    """PluginManager.build no longer calls load_dotenv itself."""
    import agents.core.plugin_manager as pm

    seen = []
    monkeypatch.setattr(pm, "load_layered_env", lambda repo, home: seen.append((repo, home)) or {})
    monkeypatch.setenv("JARVIS_USER_HOME", str(tmp_path))
    _write(tmp_path / ".env", "PROV_HOME_ONLY=1\n")

    class _Stop(Exception):
        pass

    monkeypatch.setattr(pm, "CloudLLMPlugin", lambda **_: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        pm.PluginManager().build(object())
    assert seen == [(ROOT / ".env", tmp_path / ".env")]
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
    _write(root / ".env", f"JARVIS_PORT=8081\nOPENAI_API_KEY={SECRET_VALUE}\n")
    home = tmp_path / "home"
    _write(home / ".env", "JARVIS_PORT=9000\nTELEGRAM_BOT_TOKEN=abc\n")
    env = {"JARVIS_USER_HOME": str(home), "OPENAI_API_KEY": "from-shell", "PATH": "/usr/bin"}
    check = doctor.check_config_sources(root, env)
    assert check.status == doctor.OK
    rows = {row["key"]: row for row in check.data["sources"]}
    assert rows["JARVIS_PORT"] == {"key": "JARVIS_PORT", "layer": "repo_env", "shadowed": ["user_env"]}
    assert rows["OPENAI_API_KEY"] == {"key": "OPENAI_API_KEY", "layer": "process",
                                      "shadowed": ["repo_env"]}
    assert rows["TELEGRAM_BOT_TOKEN"]["layer"] == "user_env"
    assert "PATH" not in rows                                          # not configuration
    assert "1 key set in the process environment overrides a .env value" in check.reason
    assert f"repo .env {root / '.env'} (present)" in check.detail
    assert f"data-home .env {home / '.env'} (present)" in check.detail
    assert "not configured" in doctor.check_config_sources(root, {}).detail
    text = doctor.format_report(doctor.DoctorReport(ok=True, root=str(root), checks=[check]))
    assert "OPENAI_API_KEY" in text and "process environment" in text
    assert SECRET_VALUE not in text and "from-shell" not in text and "abc" not in text
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
