"""H273 second review round — what the provenance table and the doctor still got wrong.

- B1: the hub reads more names before any .env is loaded than serve.py's four: every
  constant ``agents.web`` freezes while it is imported (the rate limit, CORS, CSP, the
  graph's Neo4j defaults …). ``READ_BEFORE_LOAD`` is now measured: a subprocess spies on
  the environment while the hub is imported, and every Nerva name read there is either
  listed as read before the load or declared as read again once it is done.
- B2: a one-case identifier can still be value material (a base32 seed or a hex digest
  line in an unquoted multi-line value). The doctor prints a name only when the hub
  reads it, it carries Nerva's prefix, ``.env.example`` declares it, or it is a one-case
  identifier with a real value (not empty, not only ``=`` padding); the rest is counted.
- B3: the guards the first round's tests did not pin (a secret listed by ``get_all``, an
  unknown stored posture, the shell's data home, the doctor's detail line, a reply
  without ``sources``, the disabled spellings, serve.py's own reads).
- B4: names the hub reads through a bound mapping (``env.get(...)``) or through
  ``*_ENV`` constants are hub names too.
- The nits: a second load recomputes what it knows; ``PYTHON_DOTENV_DISABLED`` set in
  the repo .env stops the data-home layer; a data-home .env that is the repo .env is
  present; odd hub payloads; one parse per file; ``${VAR}`` in the data home resolved in
  the hub's order; a refused token named; "1 key"; no private python-dotenv API; one
  settings connection per listing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
from agents.core import env_provenance as ep  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def scrub():
    keys: list[str] = []
    yield keys
    for key in keys:
        os.environ.pop(key, None)


# ── B1: what the hub reads before any .env is loaded ─────────────────────────────

_SPY = r"""
import os, sys
reads = []
original = os._Environ.__getitem__
def spy(self, key):
    reads.append(key)
    return original(self, key)
os._Environ.__getitem__ = spy
import agents.web  # noqa: F401  (serve.py and `uvicorn agents.web:app` both import it first)
os._Environ.__getitem__ = original
print("\n".join(sorted({key for key in reads if isinstance(key, str)})))
"""


def _declared_in_example() -> set:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))


def test_every_nerva_name_read_while_the_hub_is_imported_is_classified(tmp_path):
    env = {**os.environ, "JARVIS_HOME": str(tmp_path / "home"), "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", _SPY], cwd=ROOT, env=env, capture_output=True, text=True,
                         timeout=240)
    assert out.returncode == 0, out.stderr[-2000:]
    read = set(out.stdout.split())
    assert {"JARVIS_RATE_LIMIT", "JARVIS_CORS_ORIGINS", "NEO4J_URL"} <= read      # the spy works
    from scripts import doctor

    hub_names = doctor.hub_env_names(ROOT)
    owned = {name for name in read if name.startswith(("JARVIS_", "NERVA_", "NEO4J_"))
             or name in _declared_in_example() or name in hub_names}
    assert read >= ep.READ_AGAIN_AFTER_LOAD           # stale READ_BEFORE_LOAD entries: the start test (H273d)
    unclassified = owned - ep.READ_BEFORE_LOAD - ep.READ_AGAIN_AFTER_LOAD
    assert not unclassified, (
        f"{sorted(unclassified)} are read while the hub is imported, before any .env is loaded. "
        "List each in env_provenance.READ_BEFORE_LOAD (a .env value is not in effect) or, when "
        "the hub reads it again once the files are loaded, in READ_AGAIN_AFTER_LOAD.")
    assert not ep.READ_BEFORE_LOAD & ep.READ_AGAIN_AFTER_LOAD


def test_serve_py_reads_its_names_after_the_env_files_are_loaded():
    """serve.py loads the .env files before it builds the server (H273 third review), so
    what it reads is in effect from a file: none of it is listed as read before the load."""
    from scripts import doctor

    names = doctor.names_read_in((ROOT / "serve.py").read_text(encoding="utf-8"))
    assert {"JARVIS_HOST", "JARVIS_PORT", "JARVIS_LOG_LEVEL", "JARVIS_SHUTDOWN_TIMEOUT"} <= names
    assert names.isdisjoint(ep.READ_BEFORE_LOAD) and ep.note_for("JARVIS_PORT", ep.REPO_ENV) == ""


@pytest.mark.parametrize("key", ["JARVIS_RATE_LIMIT", "JARVIS_CORS_ORIGINS", "JARVIS_AUTO_DEEP", "NEO4J_URL",
                                 "JARVIS_ROOT_PATH"])
def test_the_note_says_the_hub_reads_it_before_the_load(key):
    note = ep.note_for(key, ep.REPO_ENV)
    assert "before the .env files are loaded" in note and "serve.py" not in note
    assert ep.note_for(key, ep.USER_ENV) == note and ep.note_for(key, ep.PROCESS) == ""
    assert ep.note_for("DEV_MODE", ep.REPO_ENV) == ""                   # read again after the load


# ── B2: no value material printed as a name ──────────────────────────────────────

SEEDS = ("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "KRSXG5CTMVRXEZLUKN2XAZLSKNSWG4TFOQ",
         "d41d8cd98f00b204e9800998ecf8427e")
UNQUOTED_SECRETS = (
    "JARVIS_TOTP_SEEDS=first\n"
    f"{SEEDS[0]}====\n"
    f"{SEEDS[1]}======\n"
    f"{SEEDS[2]}=\n"
    "OPENAI_API_KEY=sk-after\n"
    "MY_TOOL_FLAG=on\n"
    "2FA_BACKUP_EMAIL=me@example.org\n"
    "spring.profiles.active=dev\n"
)


def test_value_material_in_a_key_name_is_never_printed(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", UNQUOTED_SECRETS)
    assert set(SEEDS) <= set(ep.env_file_keys(root / ".env"))           # python-dotenv really makes them keys
    check = doctor.check_config_sources(root, {})
    report = doctor.DoctorReport(ok=True, root=str(root), checks=[check])
    text, blob = doctor.format_report(report), json.dumps(report.to_dict())
    for seed in SEEDS:
        assert seed not in text and seed not in blob
    shown = {row["key"] for row in check.data["sources"]}
    assert {"JARVIS_TOTP_SEEDS", "OPENAI_API_KEY", "MY_TOOL_FLAG"} <= shown
    assert check.status == doctor.WARN and check.reason.startswith("withheld_env_names:5")


def test_a_declared_name_is_shown_even_without_a_value(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", "NTFY_TOPIC=\n")                                # .env.example declares it
    assert "NTFY_TOPIC" not in doctor.hub_env_names(ROOT)                  # so only the declaration shows it
    check = doctor.check_config_sources(root, {})
    assert {row["key"] for row in check.data["sources"]} == {"NTFY_TOPIC"} and check.status == doctor.OK


def test_a_withheld_name_is_counted_without_a_diagnosis_it_may_not_have(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", "2FA_BACKUP_EMAIL=me@example.org\nspring.profiles.active=dev\n")
    check = doctor.check_config_sources(root, {})
    assert check.reason.startswith("withheld_env_names:2")
    assert "is unquoted or mis-escaped" not in check.reason and "may" in check.reason


# ── B3: the guards the first round left unpinned ────────────────────────────────

@pytest.fixture
def settings(tmp_path, monkeypatch):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db()
    return settings_db


def test_a_secret_whose_key_is_lost_is_unreadable_in_every_listing(settings, monkeypatch):
    class _LostKey:
        def encrypt_value(self, value):
            return "ciphertext"

        def decrypt_value(self, value):
            raise ValueError("the key is gone")

    monkeypatch.setattr(settings, "_field_cipher", _LostKey())
    settings.put_category("plugins", {"twilio_auth_token": "AC-secret"})
    everything = {row["key"]: row for row in settings.get_all()["plugins"]}
    assert everything["twilio_auth_token"]["source"] == "unreadable"


def test_an_unknown_stored_posture_neither_raises_nor_overlays(settings):
    conn = settings.get_conn()
    conn.execute("UPDATE settings SET value=? WHERE category='product' AND key='posture'", (json.dumps("bogus"),))
    conn.commit()
    conn.close()
    for rows in (settings.get_category("memory"), *settings.get_all().values()):
        assert not any("overlay" in row for row in rows)


def test_the_shells_data_home_beats_the_one_the_repo_env_names(tmp_path):
    shell_home, file_home = tmp_path / "shell-home", tmp_path / "file-home"
    _write(shell_home / ".env", "PROV_FROM_SHELL_HOME=1\n")
    _write(file_home / ".env", "PROV_FROM_FILE_HOME=1\n")
    repo = _write(tmp_path / "repo" / ".env", f"JARVIS_USER_HOME={file_home}\n")

    def home_env(merged):
        return Path(merged["JARVIS_USER_HOME"]) / ".env" if merged.get("JARVIS_USER_HOME") else None

    table = ep.derive(repo, home_env, {"JARVIS_USER_HOME": str(shell_home)})
    assert "PROV_FROM_SHELL_HOME" in table and "PROV_FROM_FILE_HOME" not in table


def test_the_doctors_detail_names_what_it_read(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    home = tmp_path / "named-home"
    _write(home / ".env", "PROV_HOME=1\n")
    _write(root / ".env", f"JARVIS_USER_HOME={home}\n")
    check = doctor.check_config_sources(root, {})
    assert f"{home / '.env'} (present)" in check.detail                  # the data home the repo .env names
    disabled = doctor.check_config_sources(root, {"PYTHON_DOTENV_DISABLED": "1"})
    assert "PYTHON_DOTENV_DISABLED is set: no .env file is loaded" in disabled.detail
    assert "data-home .env not configured" in disabled.detail            # the repo .env is not read either
    odd_user = doctor.check_config_sources(root, {"JARVIS_USER_HOME": "~nosuchuser_h273c/nerva"})
    assert odd_user.status == doctor.OK and "nosuchuser_h273c" in odd_user.detail


def test_a_hub_reply_without_sources_is_a_prediction(tmp_path):
    import urllib.error

    from scripts import doctor

    class _Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def close(self):
            pass

    def opener(request, timeout=None):
        url = getattr(request, "full_url", request)
        if url.endswith("/readyz"):
            return _Resp(b"ok")
        if url.endswith(doctor.ENV_SOURCES_PATH):
            return _Resp(json.dumps({"rows": []}).encode())
        raise urllib.error.URLError("nothing")

    _write(tmp_path / ".env", "PROV_LOCAL=1\n")
    readyz = doctor.check_readyz(opener, env={})
    check = doctor.check_config_sources(tmp_path, {}, opener=opener, readyz=readyz)
    assert check.detail.startswith("predicted") and "not a sources table" in check.detail
    assert {row["key"] for row in check.data["sources"]} == {"PROV_LOCAL"}


@pytest.mark.parametrize("value", ["1", "true", "t", "yes", "y", "TRUE", "Yes", "0", "false", "no", "n", "",
                                   "on", "2", " 1"])
def test_the_disabled_spellings_are_python_dotenvs(value, monkeypatch):
    from dotenv import main as dotenv_main

    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", value)
    assert ep.dotenv_disabled({"PYTHON_DOTENV_DISABLED": value}) is dotenv_main._load_dotenv_disabled()


# ── B4: names read through a mapping or an *_ENV constant ──────────────────────

def test_hub_names_include_mapping_reads_and_env_constants():
    from scripts import doctor

    names = doctor.hub_env_names(ROOT)
    assert {"TELEGRAM_ALLOWED_CHAT_IDS", "TELEGRAM_GROUP_REQUIRE_MENTION", "TELEGRAM_GROUP_OBSERVE"} <= names
    assert {"FORWARDED_ALLOW_IPS", "UVICORN_FORWARDED_ALLOW_IPS", "UVICORN_PROXY_HEADERS",
            "JARVIS_TRUSTED_PROXIES"} <= names


def test_the_doctor_shows_a_group_allowlist_set_in_the_shell(tmp_path):
    from scripts import doctor

    env = {"TELEGRAM_ALLOWED_CHAT_IDS": "-100", "TELEGRAM_GROUP_OBSERVE": "1", "FORWARDED_ALLOW_IPS": "*"}
    rows = {row["key"] for row in doctor.check_config_sources(tmp_path, env).data["sources"]}
    assert set(env) <= rows


# ── the nits ─────────────────────────────────────────────────────────────────────

def test_a_second_load_recomputes_what_the_files_shadow(tmp_path, scrub):
    repo = _write(tmp_path / "repo" / ".env", "PROV_C1=from-repo\n")
    home = _write(tmp_path / "home" / ".env", "PROV_C1=from-home\n")
    scrub.append("PROV_C1")
    os.environ.pop("PROV_C1", None)
    assert ep.load_layered_env(repo, home)["PROV_C1"] == {"layer": "repo_env", "shadowed": ["user_env"]}
    home.write_text("OTHER=1\n", encoding="utf-8")
    scrub.append("OTHER")
    assert ep.load_layered_env(repo, home)["PROV_C1"] == {"layer": "repo_env", "shadowed": []}


def test_a_value_replaced_between_loads_is_the_process_environments(tmp_path, scrub, monkeypatch):
    repo = _write(tmp_path / "repo" / ".env", "PROV_C1B=from-repo\n")
    scrub.append("PROV_C1B")
    os.environ.pop("PROV_C1B", None)
    ep.load_layered_env(repo, tmp_path / "none" / ".env")
    monkeypatch.setenv("PROV_C1B", "set-later")
    assert ep.load_layered_env(repo, tmp_path / "none" / ".env")["PROV_C1B"] == \
        {"layer": "process", "shadowed": ["repo_env"]}


def test_a_repo_env_that_disables_dotenv_stops_the_data_home_layer(tmp_path, scrub, monkeypatch):
    repo = _write(tmp_path / "repo" / ".env", "PYTHON_DOTENV_DISABLED=1\nPROV_C2_REPO=1\n")
    home = _write(tmp_path / "home" / ".env", "PROV_C2_HOME=1\n")
    for key in ("PYTHON_DOTENV_DISABLED", "PROV_C2_REPO", "PROV_C2_HOME"):
        monkeypatch.delenv(key, raising=False)
        scrub.append(key)
    table = ep.load_layered_env(repo, home)
    assert os.environ.get("PROV_C2_REPO") == "1" and "PROV_C2_HOME" not in os.environ   # python-dotenv's own order
    assert "PROV_C2_HOME" not in table
    assert ep.files()["user_env"]["kind"] == "disabled" and ep.files()["user_env"]["read"] is False
    derived = ep.derive(repo, home, {})
    assert "PROV_C2_REPO" in derived and "PROV_C2_HOME" not in derived


def test_a_disabled_load_says_nothing_was_read(tmp_path, monkeypatch):
    repo = _write(tmp_path / "repo" / ".env", "PROV_C2B=1\n")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    ep.load_layered_env(repo, tmp_path / "none" / ".env")
    assert ep.files()["repo_env"] == {"path": str(repo), "kind": "disabled", "present": True, "read": False}
    assert "PROV_C2B" not in os.environ


def test_a_data_home_env_that_is_the_repo_env_is_present(tmp_path, scrub):
    repo = _write(tmp_path / ".env", "PROV_C3=1\n")
    scrub.append("PROV_C3")
    ep.load_layered_env(repo, repo)
    assert ep.files()["user_env"] == {"path": str(repo), "kind": "same file as the repo .env",
                                      "present": True, "read": False}


def test_odd_hub_payloads_keep_the_table(tmp_path):
    import urllib.error

    from scripts import doctor

    payload = {"sources": [
        {"key": "JARVIS_LATE", "layer": "runtime", "shadowed": []},
        {"key": "JARVIS_ODD_STR", "layer": "process", "shadowed": "repo_env"},
        {"key": "JARVIS_ODD_INT", "layer": "process", "shadowed": 5},
    ], "files": {}}

    class _Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def close(self):
            pass

    def opener(request, timeout=None):
        url = getattr(request, "full_url", request)
        if url.endswith("/readyz"):
            return _Resp(b"ok")
        if url.endswith(doctor.ENV_SOURCES_PATH):
            return _Resp(json.dumps(payload).encode())
        raise urllib.error.URLError("nothing")

    check = doctor.check_config_sources(tmp_path, {}, opener=opener, readyz=doctor.check_readyz(opener, env={}))
    rows = {row["key"]: row for row in check.data["sources"]}
    assert rows["JARVIS_ODD_STR"]["shadowed"] == [] and rows["JARVIS_ODD_INT"]["shadowed"] == []
    assert "1 set while running" in check.reason and check.reason.startswith("3 keys:")


def test_the_doctor_parses_each_env_file_once(tmp_path, caplog, monkeypatch):
    """Once, and silently: python-dotenv's own parser names the keys (the hub's load is
    where a bad line is warned about, once; H273 third review)."""
    from scripts import doctor

    parses = []
    real = ep._bindings
    monkeypatch.setattr(ep, "_bindings", lambda text: parses.append(text) or real(text))
    root = tmp_path / "repo"
    _write(root / ".env", "GOOD=1\nthis line cannot parse ' \nALSO_GOOD=2\n")
    with caplog.at_level(logging.WARNING):
        check = doctor.check_config_sources(root, {})
    assert len(parses) == 1 and not [r for r in caplog.records if "could not parse" in r.getMessage()]
    assert {"GOOD", "ALSO_GOOD"} <= {row["key"] for row in check.data["sources"]}


def test_a_data_home_built_from_a_shell_variable_follows_the_hubs_order(tmp_path):
    shell_base, file_base = tmp_path / "shell", tmp_path / "file"
    _write(shell_base / "home" / ".env", "PROV_C8_SHELL=1\n")
    _write(file_base / "home" / ".env", "PROV_C8_FILE=1\n")
    repo = _write(tmp_path / "repo" / ".env", f"NERVA_BASE={file_base}\nJARVIS_USER_HOME=${{NERVA_BASE}}/home\n")

    def home_env(merged):
        return Path(merged["JARVIS_USER_HOME"]) / ".env" if merged.get("JARVIS_USER_HOME") else None

    table = ep.derive(repo, home_env, {"NERVA_BASE": str(shell_base)})
    assert "PROV_C8_SHELL" in table and "PROV_C8_FILE" not in table     # load_dotenv(override=False)'s order


def test_a_refused_token_is_named_and_one_key_is_one(tmp_path):
    import urllib.error

    from scripts import doctor

    class _Resp:
        def read(self):
            return b"ok"

        def close(self):
            pass

    def opener(request, timeout=None):
        url = getattr(request, "full_url", request)
        if url.endswith("/readyz"):
            return _Resp()
        raise urllib.error.HTTPError(url, 401, "no", {}, None)

    _write(tmp_path / ".env", "PROV_ONE=1\n")
    env = {"JARVIS_ADMIN_TOKEN": "adm-wrong"}
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=doctor.check_readyz(opener, env=env))
    assert "the running hub refused the admin token" in check.detail
    assert check.reason.startswith("2 keys: ")
    assert doctor.check_config_sources(tmp_path, {}).reason.startswith("1 key: ")


def test_the_load_needs_no_private_python_dotenv_api(tmp_path, scrub):
    import inspect

    source = inspect.getsource(ep)
    assert "DotEnv" not in source and "dotenv.main" not in source   # load_dotenv and dotenv.parser only
    repo = _write(tmp_path / ".env", "PROV_C10=1\n")
    scrub.append("PROV_C10")
    os.environ.pop("PROV_C10", None)
    assert ep.load_layered_env(repo, tmp_path / "none" / ".env")["PROV_C10"]["layer"] == "repo_env"
    assert os.environ["PROV_C10"] == "1"


def test_a_listing_opens_one_settings_connection(settings, monkeypatch):
    opened = []
    real = settings.get_conn

    def counting():
        opened.append(1)
        return real()

    settings.get_all()                                                    # the first call also initialises
    monkeypatch.setattr(settings, "get_conn", counting)
    settings.get_all()
    settings.get_category("mcp")
    assert len(opened) == 2


def test_the_route_with_no_load_says_what_it_would_read(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import paths

    monkeypatch.setattr(web, "ADMIN_TOKEN", "prov-admin")
    monkeypatch.setattr(ep, "_FILES", {})
    home = tmp_path / "home-without-env"
    home.mkdir()
    with TestClient(web.app) as client:
        monkeypatch.setattr(ep, "_FILES", {})            # the lifespan's own load, forgotten
        monkeypatch.setattr(paths, "user_home", lambda: home)     # a home the start did not scaffold
        files = client.get("/api/admin/env/sources", headers={"X-Admin-Token": "prov-admin"}).json()["files"]
    assert files["user_env"] == {"path": str(home / ".env"), "present": False, "read": False}
    assert files["repo_env"]["present"] is (ROOT / ".env").exists() and files["repo_env"]["read"] is False


@pytest.mark.parametrize("value", ["${A}", "x${A}y", "${MISSING}", "${MISSING:-dflt}", "${A:-dflt}", "$A",
                                   "${B}${A}", "${}", "${A", "plain", "${EMPTY:-d}"])
def test_the_expansion_is_python_dotenvs(value):
    from dotenv.variables import parse_variables

    env = {"A": "a-val", "B": "b-val", "EMPTY": ""}
    expected = "".join(atom.resolve(env) for atom in parse_variables(value))
    assert ep._interpolate(value, env) == expected


def test_the_route_says_a_skipped_file_is_present_and_unread(tmp_path, monkeypatch, scrub):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "prov-admin")
    repo = _write(tmp_path / ".env", "PROV_RT=1\n")
    scrub.append("PROV_RT")
    os.environ.pop("PROV_RT", None)
    with TestClient(web.app) as client:
        ep.load_layered_env(repo, repo)
        files = client.get("/api/admin/env/sources", headers={"X-Admin-Token": "prov-admin"}).json()["files"]
    assert files["user_env"] == {"path": str(repo), "present": True, "kind": "same file as the repo .env",
                                 "read": False}
