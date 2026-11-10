"""RB-2 — ``NERVA_<X>`` is the preferred spelling of every ``JARVIS_<X>`` variable.

The product was renamed to Nerva and every variable was still ``JARVIS_*``. Now each hub
variable is ONE variable with two spellings: ``NERVA_<X>`` (preferred) and ``JARVIS_<X>``
(deprecated, still honoured). These tests pin the mechanism on the real thing: the
``env_config`` getters at call time, the fold of the process environment, the real
``load_layered_env`` over temporary ``.env`` files, the boot guards, the child-process
environment builders and the admin routes. The whole-hub start under each spelling is
``test_rb2_env_alias_boot.py``; the source inventory is ``test_rb2_env_alias_inventory.py``.

Nothing here may print a value: every refusal and warning is checked for the variable's
name and against the values.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
# Imported here, before any test puts a token in the environment: agents.web freezes
# JARVIS_ADMIN_TOKEN into a module global when it is first imported, and a test that was
# the first to import it with a token loaded would leave every later test on the worker
# behind an admin token (the owner-from-localhost tests then answer 401).
import agents.web  # noqa: E402,F401
from agents.core import boot_guards, env_alias, env_config  # noqa: E402
from agents.core import env_provenance as ep  # noqa: E402

OLD_VALUE, NEW_VALUE = "value-from-the-old-spelling-71c2", "value-from-the-new-spelling-9e4d"

# The variables the brief names, plus one plain tuning knob. (suffix, a valid value)
NAMED = [
    ("HARDENED", "1"), ("STRICT_EGRESS", "0"), ("ALLOW_INSECURE_BIND", "1"),
    ("ADMIN_TOKEN", "admin-token-3b1f9c"), ("USER_TOKEN", "user-token-77ad02"),
    ("TRUSTED_PROXIES", "127.0.0.1/32"), ("HOME", "/srv/nerva-data"), ("USER_HOME", "/srv/nerva-home"),
    ("SAFE_MODE", "1"), ("PORT", "8123"),
]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def clean(monkeypatch):
    """No hub variable of the test set, under either spelling, and no spelling marker;
    whatever a test (or a load) puts in the environment is taken out again."""
    saved = dict(os.environ)
    for key in list(os.environ):
        if key == env_alias.MARKER or env_config.other_spelling(key):
            monkeypatch.delenv(key)
    yield monkeypatch
    for key in set(os.environ) - set(saved):
        os.environ.pop(key, None)


# ── the map and the pair rule: one function each ─────────────────────────────────

def test_the_map_goes_both_ways_for_hub_variables_only():
    assert env_config.other_spelling("JARVIS_HARDENED") == "NERVA_HARDENED"
    assert env_config.other_spelling("NERVA_HARDENED") == "JARVIS_HARDENED"
    assert env_config.other_spelling("NERVA_ROLE_VISION_MODEL") == "JARVIS_ROLE_VISION_MODEL"
    for own in ("NERVA_HUB_URL", "NERVA_WORKSPACE", "NERVA_WORKSPACE_SSO_SECRET", "NERVA_PUBLIC_PROFILE",
                "DEV_MODE", "OPENAI_API_KEY", "JARVIS_NO_SUCH_VARIABLE"):
        assert env_config.other_spelling(own) is None


def test_one_function_maps_and_one_resolves_and_everything_else_goes_through_them():
    """No second copy of the prefix arithmetic anywhere in the hub: a module that builds
    the other spelling itself would drift from the rule."""
    import re

    pattern = re.compile(r"""replace\(\s*["']JARVIS_["']|["']NERVA_["']\s*\+|\+\s*["']NERVA_["']|"""
                         r"""["']JARVIS_["']\s*\+\s*\w+\[""")
    offenders = []
    for path in [*sorted((ROOT / "agents").rglob("*.py")), *sorted((ROOT / "scripts").rglob("*.py")),
                 ROOT / "serve.py"]:
        if path.name == "env_config.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
    alias_source = (ROOT / "agents/core/env_alias.py").read_text(encoding="utf-8")
    assert "other_spelling(" in alias_source and "resolve_spellings(" in alias_source


@pytest.mark.parametrize("env, expected", [
    ({}, (None, None)),
    ({"JARVIS_PORT": "1"}, ("1", "JARVIS_PORT")),
    ({"NERVA_PORT": "2"}, ("2", "NERVA_PORT")),
    # different values: no spelling "wins" (every entry point refuses the pair); until the
    # process has stopped, the answer is what a direct os.environ reader of JARVIS_X sees
    ({"JARVIS_PORT": "1", "NERVA_PORT": "2"}, ("1", "JARVIS_PORT")),
    ({"JARVIS_PORT": "1", "NERVA_PORT": "1"}, ("1", "NERVA_PORT")),
    ({"JARVIS_PORT": "1", "NERVA_PORT": "  "}, ("1", "JARVIS_PORT")),     # blank is "not set"
    ({"JARVIS_PORT": "", "NERVA_PORT": "2"}, ("2", "NERVA_PORT")),
    ({"JARVIS_PORT": "", "NERVA_PORT": ""}, ("", "NERVA_PORT")),
])
def test_the_pair_rule(env, expected):
    assert env_config.resolve_spellings(env, "JARVIS_PORT") == expected
    assert env_config.resolve_spellings(env, "NERVA_PORT") == expected     # asked by either name


def test_a_variable_with_one_spelling_is_read_as_before():
    assert env_config.resolve_spellings({"NERVA_HUB_URL": "u"}, "NERVA_HUB_URL") == ("u", "NERVA_HUB_URL")
    assert env_config.resolve_spellings({"JARVIS_HUB_URL": "u"}, "NERVA_HUB_URL") == (None, None)
    assert env_config.resolve_spellings({"DEV_MODE": "1"}, "DEV_MODE") == ("1", "DEV_MODE")


# ── env_config's getters read both spellings at call time, with no help ──────────────

def test_every_getter_reads_the_new_spelling_set_while_running(clean):
    """monkeypatch.setenv at run time, no fold in between: the getters still see it."""
    clean.setenv("NERVA_HARDENED", "yes")
    clean.setenv("NERVA_HOST", "10.0.0.7")
    clean.setenv("NERVA_CORS_ORIGINS", "https://a.example, https://b.example")
    clean.setenv("NERVA_PORT", "8123")
    clean.setenv("NERVA_EVAL_LIVE_MIN_SCORE", "0.5")
    clean.setenv("NERVA_CALL_CONFIG", '{"twilio": {"sid": "x"}}')
    clean.setenv("NERVA_CHANNEL_SEND_RATES", "whatsapp:10,teams:30")
    assert env_config.env_flag("JARVIS_HARDENED") is True
    assert env_config.env_str("JARVIS_HOST", "127.0.0.1") == "10.0.0.7"
    assert env_config.env_list("JARVIS_CORS_ORIGINS") == ["https://a.example", "https://b.example"]
    assert env_config.env_int("JARVIS_PORT", 8080) == 8123
    assert env_config.env_float("JARVIS_EVAL_LIVE_MIN_SCORE", 0.0) == 0.5
    assert env_config.env_json_object("JARVIS_CALL_CONFIG") == {"twilio": {"sid": "x"}}
    assert env_config.env_int_map("JARVIS_CHANNEL_SEND_RATES") == {"whatsapp": 10, "teams": 30}
    assert "NERVA_HARDENED" in os.environ and "JARVIS_HARDENED" not in os.environ   # no side effect
    clean.delenv("NERVA_HARDENED")
    assert env_config.env_flag("JARVIS_HARDENED") is False                # read at call time, not cached


def test_a_malformed_flag_is_malformed_under_either_spelling(clean):
    clean.setenv("NERVA_CHANNEL_OPEN", "yse")
    assert env_config.env_flag_is_malformed("JARVIS_CHANNEL_OPEN") is True
    assert env_config.env_flag("JARVIS_CHANNEL_OPEN") is False            # junk -> the declared default
    clean.setenv("NERVA_ALLOW_INSECURE_BIND", "maybe")
    assert env_config.env_flag("JARVIS_ALLOW_INSECURE_BIND") is False     # a typo never opens the bind
    clean.setenv("NERVA_STRICT_EGRESS", "nope")
    assert env_config.env_flag("JARVIS_STRICT_EGRESS", True) is True      # ... and never relaxes egress


# ── the fold of the process environment ──────────────────────────────────────────

@pytest.mark.parametrize("suffix, value", NAMED)
def test_the_new_spelling_becomes_the_variable_the_hub_reads(suffix, value):
    env = {f"NERVA_{suffix}": value, "PATH": "/usr/bin"}
    env_alias.normalize(env)
    assert env == {f"JARVIS_{suffix}": value, "PATH": "/usr/bin", env_alias.MARKER: f"JARVIS_{suffix}"}
    again = dict(env)
    assert env_alias.normalize(again).spelling == {} and again == env     # idempotent
    assert env_alias.spelling_info(f"JARVIS_{suffix}", env) == {
        "spelling": f"NERVA_{suffix}", "preferred": f"NERVA_{suffix}", "deprecated": False}
    old = {f"JARVIS_{suffix}": value}
    env_alias.normalize(old)
    assert old == {f"JARVIS_{suffix}": value}                              # the old spelling: untouched
    assert env_alias.spelling_info(f"JARVIS_{suffix}", old)["deprecated"] is True


def test_equal_values_and_a_blank_one_are_not_a_disagreement():
    env = {"NERVA_ADMIN_TOKEN": "same", "JARVIS_ADMIN_TOKEN": "same"}
    assert env_alias.conflicts(env) == []
    env_alias.normalize(env)
    assert env == {"JARVIS_ADMIN_TOKEN": "same", env_alias.MARKER: "JARVIS_ADMIN_TOKEN"}
    # a compose file that forwards both names hands the unused one over empty
    for blank, kept, spelled in (("NERVA_HARDENED", "JARVIS_HARDENED", "JARVIS_HARDENED"),
                                 ("JARVIS_HARDENED", "NERVA_HARDENED", "NERVA_HARDENED")):
        env = {blank: "", kept: "1"}
        assert env_alias.conflicts(env) == []
        env_alias.normalize(env)
        assert env["JARVIS_HARDENED"] == "1" and "NERVA_HARDENED" not in env
        assert env_alias.spelling_info("JARVIS_HARDENED", env)["spelling"] == spelled


@pytest.mark.parametrize("suffix", [suffix for suffix, _ in NAMED]
                         + ["LOG_LEVEL", "TASK_MAX_SECONDS", "TERMINAL_TIMEOUT_S", "BACKUP_MAX_BYTES", "HUD", "AUDIT_KEY", "CHANNEL_OPEN", "TASK_MEDIATION", "ROLE_VISION_KEY", "HOST",
                            "ALLOWED_HOSTS", "PROFILE", "LM_STUDIO_URL"])
def test_a_disagreement_refuses_and_names_the_variable_never_a_value(suffix, capsys, caplog):
    env = {f"NERVA_{suffix}": NEW_VALUE, f"JARVIS_{suffix}": OLD_VALUE, "PATH": "/usr/bin"}
    before = dict(env)
    with caplog.at_level(logging.DEBUG):
        folded = env_alias.normalize(env)
        assert env == before                              # left exactly as found: nothing is picked
        assert folded.refused == (f"JARVIS_{suffix}",)
        assert env_alias.conflicts(env) == [f"JARVIS_{suffix}"]
        with pytest.raises(SystemExit) as refused:
            env_alias.refuse_conflicts(env)
    message = str(refused.value)
    assert message.startswith("Refusing to start") and f"NERVA_{suffix}" in message and f"JARVIS_{suffix}" in message
    said = message + caplog.text + "".join(capsys.readouterr())
    assert NEW_VALUE not in said and OLD_VALUE not in said


def test_no_variable_has_a_spelling_that_wins(clean):
    """The rule has no exception list: whatever the variable, two different values in one
    layer are refused, and nothing is folded, warned about or picked."""
    assert not hasattr(env_config, "NERVA_WINS_ON_CONFLICT") and not hasattr(env_alias, "refuses_on_conflict")
    assert "overridden" not in env_alias.Fold._fields
    for suffix in sorted(env_config.HUB_ENV_SUFFIXES) + ["ROLE_VISION_MODEL", "VLM_PRESET", "TERMINAL_SSH_HOSTS"]:
        env = {f"NERVA_{suffix}": NEW_VALUE, f"JARVIS_{suffix}": OLD_VALUE}
        folded = env_alias.normalize(env)
        assert folded.refused == (f"JARVIS_{suffix}",) and folded.spelling == {}, suffix
        assert env == {f"NERVA_{suffix}": NEW_VALUE, f"JARVIS_{suffix}": OLD_VALUE}, suffix
        assert env_alias.conflicts(env) == [f"JARVIS_{suffix}"], suffix
        # and the two kinds of reader agree on what they see meanwhile
        assert env_config.resolve_spellings(env, f"JARVIS_{suffix}")[0] == env[f"JARVIS_{suffix}"]
    clean.setenv("NERVA_PORT", "9000")
    clean.setenv("JARVIS_PORT", "8080")
    assert env_config.env_int("JARVIS_PORT", 0) == int(os.environ["JARVIS_PORT"]) == 8080


def test_the_process_fold_is_real_and_the_hub_reads_the_variable(clean):
    clean.setenv("NERVA_STRICT_EGRESS", "0")
    clean.setenv("NERVA_TRUSTED_PROXIES", "127.0.0.1/32")
    env_alias.normalize_process_env()
    assert os.environ["JARVIS_STRICT_EGRESS"] == "0" and "NERVA_STRICT_EGRESS" not in os.environ
    assert os.environ.get("JARVIS_TRUSTED_PROXIES") == "127.0.0.1/32"     # a direct reader's read
    from agents.core import proxy_trust

    assert [str(net) for net in proxy_trust.resolve_trusted_proxies()] == ["127.0.0.1/32"]


def test_importing_the_package_folds_the_environment_before_anything_reads_it():
    """A fresh interpreter: the fold is the first statement of ``agents`` and of
    ``agents.core`` (the package under either of its import names)."""
    import subprocess

    probe = ("import os, json, sys\n"
             "sys.path.insert(0, 'agents')\n"
             "import PACKAGE\n"
             "print(json.dumps({k: v for k, v in os.environ.items() if k.startswith(('NERVA_H', 'JARVIS_H', '_NERVA'))}))\n")
    env = {key: value for key, value in os.environ.items()
           if not env_config.other_spelling(key) and key != env_alias.MARKER}
    env.update({"NERVA_HARDENED": "1", "NERVA_HUB_URL": "http://127.0.0.1:1", "PYTHONDONTWRITEBYTECODE": "1"})
    for package in ("agents", "agents.core", "core", "agents.core.env_config", "core.paths"):
        out = subprocess.run([sys.executable, "-c", probe.replace("PACKAGE", package)], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-2000:]
        assert json.loads(out.stdout.strip().splitlines()[-1]) == {
            "JARVIS_HARDENED": "1", "NERVA_HUB_URL": "http://127.0.0.1:1",
            env_alias.MARKER: "JARVIS_HARDENED"}, package
    first = [line.strip() for line in (ROOT / "agents/__init__.py").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.strip().startswith(("#", '"""'))][0]
    assert first.startswith("from . import core")


# ── the real load: layers, attribution, the process-only names ───────────────────

@pytest.fixture
def files(tmp_path, clean):
    def make(repo_text: str, home_text: str | None = None):
        repo = _write(tmp_path / "repo" / ".env", repo_text)
        home = _write(tmp_path / "home" / ".env", home_text) if home_text is not None else None
        return repo, home

    return make


@pytest.mark.parametrize("suffix, value", [pair for pair in NAMED if pair[0] != "HOME"])
def test_a_new_spelling_in_a_dotenv_file_sets_the_variable_the_hub_reads(files, suffix, value):
    repo, _ = files(f"NERVA_{suffix}={value}\n")
    table = ep.load_layered_env(repo, None)
    assert os.environ[f"JARVIS_{suffix}"] == value and f"NERVA_{suffix}" not in os.environ
    assert table[f"JARVIS_{suffix}"] == {"layer": "repo_env", "shadowed": []}
    assert f"NERVA_{suffix}" not in table
    assert ep.spelling(f"JARVIS_{suffix}") == {"spelling": f"NERVA_{suffix}", "preferred": f"NERVA_{suffix}",
                                               "deprecated": False}
    assert ep.provenance()[f"JARVIS_{suffix}"]["layer"] == "repo_env"


def test_the_same_file_in_the_old_spelling_loads_to_the_same_environment(files, tmp_path):
    body = "".join(f"{{p}}_{suffix}={value}\n" for suffix, value in NAMED if suffix != "HOME")
    repo, _ = files(body.format(p="NERVA"))
    new_table = ep.load_layered_env(repo, None)
    new_env = {k: v for k, v in os.environ.items() if env_config.other_spelling(k)}
    for key in new_env:
        os.environ.pop(key)
    os.environ.pop(env_alias.MARKER, None)
    old = _write(tmp_path / "old" / ".env", body.format(p="JARVIS"))
    old_table = ep.load_layered_env(old, None)
    old_env = {k: v for k, v in os.environ.items() if env_config.other_spelling(k)}
    assert new_env == old_env and len(new_env) == len(NAMED) - 1
    assert {k: v for k, v in new_table.items() if k in new_env} == {k: v for k, v in old_table.items() if k in old_env}
    assert all(ep.spelling(key)["deprecated"] for key in old_env)


@pytest.mark.parametrize("process, in_file", [("JARVIS", "NERVA"), ("NERVA", "JARVIS"), ("NERVA", "NERVA")])
def test_a_dotenv_value_never_overrides_a_process_value_whatever_the_spellings(files, clean, process, in_file):
    """The posture case that must not fail open: the process hardens, a file un-hardens."""
    clean.setenv(f"{process}_HARDENED", "1")
    clean.setenv(f"{process}_ADMIN_TOKEN", "process-token-55aa")
    repo, home = files(f"{in_file}_HARDENED=0\n{in_file}_ADMIN_TOKEN=file-token-11bb\n",
                       f"{in_file}_HARDENED=0\n")
    env_alias.normalize_process_env()               # what importing the package did at start
    table = ep.load_layered_env(repo, home)
    assert os.environ["JARVIS_HARDENED"] == "1" and os.environ["JARVIS_ADMIN_TOKEN"] == "process-token-55aa"
    assert "NERVA_HARDENED" not in os.environ and "NERVA_ADMIN_TOKEN" not in os.environ
    assert table["JARVIS_HARDENED"] == {"layer": "process", "shadowed": ["repo_env", "user_env"]}
    assert table["JARVIS_ADMIN_TOKEN"] == {"layer": "process", "shadowed": ["repo_env"]}
    assert env_config.env_flag("JARVIS_HARDENED") is True
    assert ep.spelling("JARVIS_HARDENED")["spelling"] == f"{process}_HARDENED"   # the layer's own spelling


def test_the_first_file_wins_over_the_second_whatever_the_spellings(files):
    repo, home = files("JARVIS_STRICT_EGRESS=1\nNERVA_SAFE_MODE=1\n",
                       "NERVA_STRICT_EGRESS=0\nJARVIS_SAFE_MODE=0\nNERVA_USER_TOKEN=home-token-90ce\n")
    table = ep.load_layered_env(repo, home)
    assert os.environ["JARVIS_STRICT_EGRESS"] == "1" and os.environ["JARVIS_SAFE_MODE"] == "1"
    assert table["JARVIS_STRICT_EGRESS"] == {"layer": "repo_env", "shadowed": ["user_env"]}
    assert table["JARVIS_SAFE_MODE"] == {"layer": "repo_env", "shadowed": ["user_env"]}
    assert table["JARVIS_USER_TOKEN"] == {"layer": "user_env", "shadowed": []}
    assert ep.spelling("JARVIS_STRICT_EGRESS")["deprecated"] is True
    assert ep.spelling("JARVIS_SAFE_MODE")["deprecated"] is False
    assert not [key for key in os.environ if key.startswith("NERVA_") and env_config.other_spelling(key)]


@pytest.mark.parametrize("name", sorted(ep.FROM_PROCESS_ONLY))
def test_a_process_only_name_is_left_out_under_the_new_spelling_exactly_as_under_the_old(files, name, tmp_path):
    new = "NERVA_" + name[len("JARVIS_"):]
    repo, _ = files(f"{new}={tmp_path / 'elsewhere'}\nNERVA_PORT=8123\n")
    table = ep.load_layered_env(repo, None)
    assert name not in os.environ and new not in os.environ           # recorded, never in effect
    assert table[name] == {"layer": "repo_env", "shadowed": []}
    assert ep.provenance()[name]["layer"] == "repo_env"
    assert ep.note_for(name, "repo_env") == ep.PROCESS_ONLY_NOTE
    assert os.environ["JARVIS_PORT"] == "8123"
    assert name not in env_alias.preferred_supplied()                 # nothing in effect to attribute
    assert ep.after_repo_layer(repo, {}).get(name) is None and ep.hub_value(new, {}) is None


def test_read_again_and_before_load_names_keep_their_meaning_under_the_new_spelling(files):
    repo, _ = files("NERVA_ADMIN_TOKEN=file-admin-4d2e\nNERVA_TRUSTED_PROXIES=127.0.0.1/32\n"
                    "NERVA_RATE_LIMIT=9\nNERVA_USER_HOME=/srv/x\n")
    ep.load_layered_env(repo, None)
    for name in ("JARVIS_ADMIN_TOKEN", "JARVIS_TRUSTED_PROXIES"):
        assert name in ep.READ_AGAIN_AFTER_LOAD and name in os.environ    # in effect: read again
        assert ep.note_for(name, "repo_env") == ""
    assert ep.note_for("JARVIS_RATE_LIMIT", "repo_env") == ep.BEFORE_LOAD_NOTE
    assert ep.note_for("JARVIS_USER_HOME", "repo_env") == ep.SPLIT_NOTES["JARVIS_USER_HOME"]
    import agents.web as web

    assert web._admin_env_token() == (web.ADMIN_TOKEN or "file-admin-4d2e")


@pytest.mark.parametrize("suffix", ["HARDENED", "ADMIN_TOKEN", "STRICT_EGRESS", "TRUSTED_PROXIES", "USER_HOME",
                                    "SAFE_MODE", "ALLOW_INSECURE_BIND", "USER_TOKEN"])
def test_a_file_that_sets_both_spellings_differently_stops_the_load(files, suffix, capsys, caplog):
    repo, home = files("PROV_FINE=1\n", f"NERVA_{suffix}={NEW_VALUE}\nJARVIS_{suffix}={OLD_VALUE}\n")
    with caplog.at_level(logging.DEBUG), pytest.raises(SystemExit) as refused:
        ep.load_layered_env(repo, home)
    message = str(refused.value)
    assert f"NERVA_{suffix}" in message and f"JARVIS_{suffix}" in message and "data-home .env" in message
    said = message + caplog.text + "".join(capsys.readouterr())
    assert NEW_VALUE not in said and OLD_VALUE not in said


def test_the_process_environment_disagreeing_stops_the_load_before_a_file_is_read(files, clean):
    clean.setenv("NERVA_HARDENED", "0")
    clean.setenv("JARVIS_HARDENED", "1")
    repo, _ = files("PROV_NEVER_LOADED=1\n")
    with pytest.raises(SystemExit) as refused:
        ep.load_layered_env(repo, None)
    assert "NERVA_HARDENED / JARVIS_HARDENED" in str(refused.value) and "process environment" in str(refused.value)
    assert "PROV_NEVER_LOADED" not in os.environ


def test_a_file_setting_any_variable_twice_differently_stops_the_load(files):
    """PORT and LOG_LEVEL were once "NERVA wins" knobs: they are refused like the rest."""
    for suffix in ("PORT", "LOG_LEVEL", "TASK_MAX_SECONDS"):
        repo, _ = files(f"JARVIS_{suffix}=8001\nNERVA_{suffix}=8002\n")
        with pytest.raises(SystemExit) as refused:
            ep.load_layered_env(repo, None)
        assert f"NERVA_{suffix} / JARVIS_{suffix}" in str(refused.value) and "repo .env" in str(refused.value)
        assert f"JARVIS_{suffix}" not in os.environ and f"NERVA_{suffix}" not in os.environ   # nothing in effect
    repo, _ = files("JARVIS_LOG_LEVEL=info\nNERVA_LOG_LEVEL=info\nNERVA_PORT=\nJARVIS_PORT=8001\n")
    ep.load_layered_env(repo, None)                       # equal, and blank beside a value: fine
    assert os.environ["JARVIS_LOG_LEVEL"] == "info" and os.environ["JARVIS_PORT"] == "8001"


def test_the_predictions_agree_with_the_load(files, clean, tmp_path):
    """The doctor's offline table and ``hub_value`` follow the same fold."""
    clean.setenv("NERVA_USER_TOKEN", "shell-user-token")
    home_dir = tmp_path / "home"
    repo, home = files(f"NERVA_HARDENED=1\nJARVIS_PORT=8001\nNERVA_USER_TOKEN=file\nNERVA_USER_HOME={home_dir}\n",
                       "NERVA_PORT=9000\nNERVA_AUDIT_KEY=audit-key-from-home\n")
    shell = dict(os.environ)
    derived = ep.derive(repo, lambda env: Path(env["JARVIS_USER_HOME"]) / ".env", shell)
    spellings, conflicts, refused, roots = ep.derive_alias(
        repo, lambda env: Path(env["JARVIS_USER_HOME"]) / ".env", shell)
    merged = ep.after_repo_layer(repo, shell)
    assert merged["JARVIS_HARDENED"] == "1" and merged["JARVIS_USER_TOKEN"] == "shell-user-token"
    assert "NERVA_HARDENED" not in merged
    table = ep.load_layered_env(repo, lambda: Path(os.environ["JARVIS_USER_HOME"]) / ".env")
    for key in ("JARVIS_HARDENED", "JARVIS_PORT", "JARVIS_USER_TOKEN", "JARVIS_AUDIT_KEY", "JARVIS_USER_HOME"):
        assert derived[key] == table[key], key
        assert spellings[key] == ep.spelling(key)["spelling"], key
    assert table["JARVIS_PORT"] == {"layer": "repo_env", "shadowed": ["user_env"]}
    assert table["JARVIS_USER_TOKEN"] == {"layer": "process", "shadowed": ["repo_env"]}
    assert spellings["JARVIS_PORT"] == "JARVIS_PORT" and spellings["JARVIS_AUDIT_KEY"] == "NERVA_AUDIT_KEY"
    assert conflicts == {} and refused == {} and roots == {}
    _write(repo, "NERVA_HARDENED=1\nJARVIS_HARDENED=0\n")
    assert ep.derive_alias(repo, None, {"NERVA_ADMIN_TOKEN": "a", "JARVIS_ADMIN_TOKEN": "b"})[1] == {
        "process": ["JARVIS_ADMIN_TOKEN"], "repo_env": ["JARVIS_HARDENED"]}


def test_a_file_cannot_write_the_hubs_own_note_of_spellings(files):
    """The marker is names only and the hub's own: a .env line claiming the preferred
    spelling for a variable changes nothing and is not configuration."""
    repo, _ = files(f"{env_alias.MARKER}=JARVIS_PORT,JARVIS_ADMIN_TOKEN\nJARVIS_PORT=8001\n")
    table = ep.load_layered_env(repo, None)
    assert env_alias.MARKER not in os.environ and env_alias.MARKER not in table
    assert ep.spelling("JARVIS_PORT")["deprecated"] is True


def test_a_profile_env_is_folded_like_any_layer(files, clean, tmp_path):
    """H689b: a profile reads only its own .env — through the same load."""
    profile_env = _write(tmp_path / "profiles" / "work" / ".env",
                         "NERVA_ADMIN_TOKEN=profile-admin-8c1a\nNERVA_HOME=/elsewhere\nNERVA_HARDENED=1\n")
    table = ep.load_layered_env(None, profile_env)
    assert os.environ["JARVIS_ADMIN_TOKEN"] == "profile-admin-8c1a" and os.environ["JARVIS_HARDENED"] == "1"
    assert "JARVIS_HOME" not in os.environ and table["JARVIS_HOME"]["layer"] == "user_env"
    assert not [key for key in os.environ if key.startswith("NERVA_") and env_config.other_spelling(key)]


# ── the boot guards ─────────────────────────────────────────────────────────────

def test_the_parse_guard_refuses_a_typo_under_the_new_spelling(clean):
    for name in ("CHANNEL_OPEN", "CHANNEL_PAIRING"):
        clean.setenv(f"NERVA_{name}", "treu")
        env_alias.normalize_process_env()
        with pytest.raises(SystemExit) as refused:
            boot_guards.assert_parseable_posture_flags()
        assert f"NERVA_{name}" in str(refused.value) and "treu" not in str(refused.value)
        os.environ.pop(f"JARVIS_{name}")           # the fold put it there: not monkeypatch's to restore
        os.environ.pop(env_alias.MARKER, None)
    with pytest.raises(SystemExit):                                       # a mapping of the caller's own
        boot_guards.assert_parseable_posture_flags({"NERVA_CHANNEL_OPEN": "treu"})
    clean.setenv("NERVA_TASK_MEDIATION", "enfroce")
    env_alias.normalize_process_env()
    with pytest.raises(SystemExit):
        boot_guards.assert_parseable_posture_flags()


def test_the_guards_refuse_a_disagreement_before_they_parse_anything(clean):
    clean.setenv("NERVA_HARDENED", "0")
    clean.setenv("JARVIS_HARDENED", "1")
    for guard in (boot_guards.assert_parseable_posture_flags, boot_guards.enforce_boot_posture,
                  boot_guards.assert_front_door):
        with pytest.raises(SystemExit) as refused:
            guard()
        assert "NERVA_HARDENED / JARVIS_HARDENED" in str(refused.value)
    with pytest.raises(SystemExit) as refused:
        boot_guards.assert_front_door({"NERVA_CHANNEL_OPEN": "1", "JARVIS_CHANNEL_OPEN": "0"})
    assert "JARVIS_CHANNEL_OPEN" in str(refused.value)


def test_the_bind_guard_reads_the_token_and_the_acknowledgement_under_either_spelling(clean, capsys):
    with pytest.raises(SystemExit):
        boot_guards.assert_safe_bind("0.0.0.0")                           # nothing set: refused
    for name, value in (("NERVA_ADMIN_TOKEN", "t-9f31ab"), ("NERVA_USER_TOKEN", "u-9f31ab"),
                        ("NERVA_ALLOW_INSECURE_BIND", "1")):
        clean.setenv(name, value)
        boot_guards.assert_safe_bind("0.0.0.0")                           # set while running, no fold
        clean.delenv(name)
    clean.setenv("NERVA_ALLOW_INSECURE_BIND", "ture")                     # a typo does not open the bind
    with pytest.raises(SystemExit):
        boot_guards.assert_safe_bind("0.0.0.0")
    assert "t-9f31ab" not in "".join(capsys.readouterr())


def test_the_front_door_is_judged_on_a_mapping_spelled_the_new_way(clean):
    """A configured bot with pairing switched off is refused; the acknowledgement is
    honoured — the same verdicts as the old spelling, from a caller's own mapping."""
    base = {"TELEGRAM_BOT_TOKEN": "123:abc"}
    for prefix in ("JARVIS", "NERVA"):
        with pytest.raises(SystemExit) as refused:
            boot_guards.assert_front_door({**base, f"{prefix}_CHANNEL_PAIRING": "0"})
        assert "would answer any sender" in str(refused.value)
        boot_guards.assert_front_door({**base, f"{prefix}_CHANNEL_PAIRING": "0", f"{prefix}_CHANNEL_OPEN": "1"})
        with pytest.raises(SystemExit):
            boot_guards.assert_front_door({**base, f"{prefix}_TRUSTED_PROXIES": "*"})
        with pytest.raises(SystemExit) as refused:
            boot_guards.assert_front_door({f"{prefix}_WEBHOOK_CHANNELS": '{"a": {"secret": "s"}}',
                                           f"{prefix}_CHANNEL_PAIRING": "off"})
        assert "webhook channel" in str(refused.value)


def test_hardening_under_the_new_spelling_has_the_same_preconditions(clean):
    from agents.core import http_client
    from agents.core.security import hardened

    clean.setenv("NERVA_HARDENED", "1")
    clean.setenv("NERVA_STRICT_EGRESS", "0")                              # the downgrade is ignored
    env_alias.normalize_process_env()
    assert hardened.enabled() and hardened.strict_egress_forced() and http_client.strict_egress_enabled()
    assert hardened.mutating_mcp_blocked() and hardened.missing_audit_key()
    with pytest.raises(SystemExit) as refused:
        boot_guards.assert_hardened_posture()                              # no audit key: refuse
    assert "JARVIS_AUDIT_KEY" in str(refused.value)
    clean.setenv("NERVA_AUDIT_KEY", "audit-key-22c1")
    env_alias.normalize_process_env()
    boot_guards.assert_hardened_posture()
    assert hardened.posture()["audit_key_present"] is True


def test_safe_mode_switch_wins_over_either_spelling_of_the_variable(clean):
    import serve
    from agents.core import safe_mode

    for spelled in ("NERVA_SAFE_MODE", "JARVIS_SAFE_MODE"):
        clean.setenv(spelled, "0")
        assert serve.apply_safe_mode_switch(["--safe-mode"]) is True
        env_alias.normalize_process_env()
        assert env_alias.conflicts() == [] and safe_mode.enabled() is True
        os.environ.pop("JARVIS_SAFE_MODE")
    clean.setenv("NERVA_SAFE_MODE", "1")
    assert safe_mode.enabled() is True                                    # the variable alone, new spelling


# ── child processes and sandboxes: what a child saw, it still sees ─────────────────

def _host_env(prefix: str) -> dict[str, str]:
    env = {"PATH": "/usr/bin", "HOME": "/home/nerva", "LANG": "C.UTF-8", "OPENAI_API_KEY": "sk-zzzz"}
    env.update({f"{prefix}_{suffix}": value for suffix, value in NAMED})
    env.update({f"{prefix}_PROFILE": "work", f"{prefix}_ENV": "prod", f"{prefix}_AUDIT_KEY": "audit-1",
                f"{prefix}_MCP_STDIO_ALLOWED_ENV": "JARVIS_PORT,OPENAI_API_KEY",
                f"{prefix}_LM_STUDIO_URL": "http://127.0.0.1:1234"})
    return env


def test_every_child_environment_is_the_same_whichever_spelling_the_operator_used():
    from agents.core.environments import scrub_child_env
    from agents.core.mcp.client import stdio_env_baseline

    old, new = _host_env("JARVIS"), env_alias.normalized(_host_env("NERVA"))
    new.pop(env_alias.MARKER)
    assert new == old                                   # the folded environment IS the old one
    scrubbed = scrub_child_env(old)
    assert scrub_child_env(env_alias.normalized(_host_env("NERVA"))) == scrubbed
    assert {key for key in scrubbed if key.startswith(("JARVIS_", "NERVA_", "_NERVA"))} == {
        "JARVIS_HOME", "JARVIS_PROFILE", "JARVIS_ENV"}
    baseline = stdio_env_baseline(dict(old))
    assert stdio_env_baseline(env_alias.normalized(_host_env("NERVA"))) == baseline
    assert baseline["JARVIS_PORT"] == "8123"            # the owner's allowlist names it, the value arrives
    assert not [key for key in baseline if key.startswith(("NERVA_", "_NERVA")) or "TOKEN" in key]


def test_a_new_spelling_never_passes_a_filter_that_stops_the_old_one():
    """Even un-folded (set while running): no NERVA_ credential or control name slips
    through a child-environment builder or a skill's declaration."""
    from agents.core import code_env
    from agents.core.environments import scrub_child_env
    from agents.core.mcp.client import stdio_env_baseline

    raw = _host_env("NERVA")
    raw[env_alias.MARKER] = "JARVIS_ADMIN_TOKEN"
    for built in (scrub_child_env(raw), stdio_env_baseline(dict(raw))):
        assert not [key for key in built if key.startswith(("NERVA_", "_NERVA"))], sorted(built)
        assert "admin-token-3b1f9c" not in built.values() and "user-token-77ad02" not in built.values()
    for name in ("JARVIS_ADMIN_TOKEN", "NERVA_ADMIN_TOKEN", "NERVA_USER_TOKEN", "NERVA_HARDENED", "NERVA_HOME",
                 "NERVA_RPC_DIR", "JARVIS_RPC_DIR", "NERVA_TOOL_RPC_TOKEN", "NERVA_WORKSPACE_SSO_SECRET",
                 "NERVA_WORKSPACE_SETUP_CODE", "NERVA_STRICT_EGRESS", "_NERVA_ENV_PREFERRED"):
        assert code_env._passable_name(name) is False, name
    assert code_env._passable_name("MY_TOOL_SETTING") is True


def test_log_redaction_and_masking_know_a_credential_under_either_spelling(clean):
    from agents.core import log_tail

    for name in ("NERVA_ADMIN_TOKEN", "NERVA_USER_TOKEN", "NERVA_AUDIT_KEY", "NERVA_SECRET_KEY",
                 "NERVA_ROLE_VISION_KEY", "NERVA_BACKUP_KEY", "NERVA_NOUS_CLIENT_ID"):
        old = "JARVIS_" + name[len("NERVA_"):]
        assert ep.masked(name) and ep.masked(old) and ep.hub_credential(name) and ep.hub_credential(old)
    clean.setenv("NERVA_ADMIN_TOKEN", "runtime-secret-value-5510")
    assert "runtime-secret-value-5510" in log_tail._known_secret_values()


# ── the admin routes ────────────────────────────────────────────────────────────

@pytest.fixture
def admin(monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "rb2-admin")
    with TestClient(web.app) as client:
        yield client


def test_the_env_routes_show_one_masked_variable_and_which_spelling_supplied_it(admin, files, clean):
    clean.setenv("NERVA_USER_TOKEN", "shell-user-token-6a6a")
    clean.setenv("JARVIS_HOST", "127.0.0.1")
    repo, home = files("NERVA_AUDIT_KEY=file-audit-key-0b0b\nJARVIS_PORT=8001\nNERVA_HOME=/nowhere\n",
                       "NERVA_PORT=9000\nJARVIS_AUDIT_KEY=home-audit\n")
    env_alias.normalize_process_env()
    ep.load_layered_env(repo, home)
    headers = {"X-Admin-Token": "rb2-admin"}
    shown = admin.get("/api/admin/env", headers=headers).json()
    assert shown["JARVIS_USER_TOKEN"] != "shell-user-token-6a6a" and shown["JARVIS_AUDIT_KEY"] != "file-audit-key-0b0b"
    assert not [key for key in shown if key.startswith(("NERVA_USER", "NERVA_AUDIT", "NERVA_PORT", "_NERVA"))]
    reply = admin.get("/api/admin/env/sources", headers=headers)
    assert reply.status_code == 200
    for value in ("shell-user-token-6a6a", "file-audit-key-0b0b", "home-audit", "9000", "8001"):
        assert value not in reply.text
    rows = {row["key"]: row for row in reply.json()["sources"]}
    assert env_alias.MARKER not in rows and "NERVA_USER_TOKEN" not in rows
    assert rows["JARVIS_USER_TOKEN"] == {
        "key": "JARVIS_USER_TOKEN", "layer": "process", "label": "process environment", "shadowed": [],
        "masked": True, "spelling": "NERVA_USER_TOKEN", "preferred": "NERVA_USER_TOKEN", "deprecated": False}
    assert rows["JARVIS_AUDIT_KEY"]["layer"] == "repo_env" and rows["JARVIS_AUDIT_KEY"]["shadowed"] == ["user_env"]
    assert rows["JARVIS_AUDIT_KEY"]["masked"] is True and rows["JARVIS_AUDIT_KEY"]["deprecated"] is False
    assert rows["JARVIS_PORT"]["spelling"] == "JARVIS_PORT" and rows["JARVIS_PORT"]["deprecated"] is True
    assert rows["JARVIS_PORT"]["preferred"] == "NERVA_PORT" and rows["JARVIS_PORT"]["shadowed"] == ["user_env"]
    assert rows["JARVIS_HOST"]["deprecated"] is True and rows["JARVIS_HOST"]["layer"] == "process"
    assert rows["JARVIS_HOME"]["note"] == ep.PROCESS_ONLY_NOTE          # left out, and said so
    assert "spelling" not in rows["PATH"] if "PATH" in rows else True   # not a hub variable


# ── the doctor and the CLI ────────────────────────────────────────────────────────

def test_the_doctor_marks_the_old_spelling_and_fails_on_a_disagreement(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", "JARVIS_PORT=8081\nNERVA_HARDENED=1\nNERVA_AUDIT_KEY=doctor-audit-key-1f\n")
    env = {"NERVA_ADMIN_TOKEN": "doctor-admin-token-2e", "JARVIS_HOST": "127.0.0.1", "PATH": "/usr/bin"}
    check = doctor.check_config_sources(root, env)
    assert check.status == doctor.OK
    rows = {row["key"]: row for row in check.data["sources"]}
    assert rows["JARVIS_HARDENED"] == {"key": "JARVIS_HARDENED", "layer": "repo_env", "shadowed": []}
    assert rows["JARVIS_ADMIN_TOKEN"]["layer"] == "process" and "NERVA_ADMIN_TOKEN" not in rows
    assert check.data["deprecated_spellings"] == {"JARVIS_PORT": "NERVA_PORT", "JARVIS_HOST": "NERVA_HOST"}
    assert "2 keys use the deprecated JARVIS_ spelling" in check.reason
    report = doctor.format_report(doctor.DoctorReport(ok=True, root=str(root), checks=[check]))
    assert "[deprecated spelling: use NERVA_PORT]" in report and "use NERVA_HARDENED" not in report
    assert "doctor-admin-token-2e" not in report and "doctor-audit-key-1f" not in report

    _write(root / ".env", f"NERVA_HARDENED={NEW_VALUE}\nJARVIS_HARDENED={OLD_VALUE}\n")
    bad = doctor.check_config_sources(root, {**env, "JARVIS_ADMIN_TOKEN": "another-admin-token"})
    assert bad.status == doctor.FAIL and bad.reason.startswith("env_spelling_conflict:JARVIS_ADMIN_TOKEN,JARVIS_HARDENED")
    assert bad.data["spelling_conflicts"] == {"process": ["JARVIS_ADMIN_TOKEN"], "repo_env": ["JARVIS_HARDENED"]}
    text = doctor.format_report(doctor.DoctorReport(ok=False, root=str(root), checks=[bad])) + json.dumps(bad.data)
    for value in (NEW_VALUE, OLD_VALUE, "doctor-admin-token-2e", "another-admin-token"):
        assert value not in text


def test_the_doctor_reads_the_hubs_own_account_of_the_spellings(tmp_path):
    from scripts import doctor

    payload = {"sources": [
        {"key": "JARVIS_PORT", "layer": "process", "label": "process environment", "shadowed": [], "masked": False,
         "spelling": "JARVIS_PORT", "preferred": "NERVA_PORT", "deprecated": True},
        {"key": "JARVIS_HOST", "layer": "process", "label": "process environment", "shadowed": [], "masked": False,
         "spelling": "NERVA_HOST", "preferred": "NERVA_HOST", "deprecated": False},
        {"key": "JARVIS_LOG_LEVEL", "layer": "process", "shadowed": [], "spelling": "bad\x1b[2J"},
    ], "files": {}}

    class _Reply:
        status = 200

        def read(self):
            return json.dumps(payload).encode()

    check = doctor.check_config_sources(tmp_path, {}, opener=lambda request, timeout=None: _Reply(),
                                        readyz=doctor.Check("readyz", doctor.OK, "ready"))
    assert check.data["deprecated_spellings"] == {"JARVIS_PORT": "NERVA_PORT", "JARVIS_LOG_LEVEL": "NERVA_LOG_LEVEL"}


def test_the_cli_refuses_a_variable_set_twice_differently_and_lets_the_doctor_explain(clean, tmp_path):
    """Both ways into the command (``scripts/nerva.py`` and ``python -m agents.cli``), in a
    fresh interpreter: a credential or a root under both spellings, differently, is refused
    by name; one spelling works; and ``nerva doctor`` still runs to say what is wrong."""
    import subprocess

    base = {key: value for key, value in os.environ.items()
            if not env_config.other_spelling(key) and key != env_alias.MARKER}
    base.update({"PYTHONDONTWRITEBYTECODE": "1", "NERVA_HUB_URL": "http://127.0.0.1:9"})

    def run(entry, argv, extra):
        out = subprocess.run([sys.executable, *entry, *argv], cwd=ROOT, env={**base, **extra},
                             capture_output=True, text=True, timeout=180)
        return out.returncode, out.stdout, out.stderr

    for entry in (["scripts/nerva.py"], ["-m", "agents.cli"]):
        for suffix in ("ADMIN_TOKEN", "HOME", "HARDENED"):
            pair = {f"NERVA_{suffix}": NEW_VALUE, f"JARVIS_{suffix}": OLD_VALUE}
            code, out, err = run(entry, ["status"], pair)
            assert code == 2 and f"NERVA_{suffix} / JARVIS_{suffix}" in err, (entry, suffix, err[-500:])
            assert NEW_VALUE not in out + err and OLD_VALUE not in out + err
            # a verb that diagnoses or repairs a configuration is never refused: it says so, and runs
            code, out, err = run(entry, ["config", "env-path"], pair)
            assert code == 0 and "repo .env:" in out, (entry, suffix, err[-500:])
            assert "warning: the hub will not start" in err and f"NERVA_{suffix} / JARVIS_{suffix}" in err
            assert NEW_VALUE not in err and OLD_VALUE not in err
            if suffix != "HOME":             # (the data root is what `config env-path` is asked to show)
                assert NEW_VALUE not in out and OLD_VALUE not in out
        code, out, err = run(entry, ["config", "path"], {"NERVA_HOME": str(tmp_path / "data")})
        assert code == 0 and str(tmp_path / "data") in out, err[-500:]      # the new spelling names the root
        code, out, err = run(entry, ["-p", "work", "status"],
                             {"NERVA_PORT": "1", "JARVIS_PORT": "2"})         # any variable: refused
        assert code == 2 and "NERVA_PORT / JARVIS_PORT" in err, err[-500:]
        assert "under the SAME spelling the launcher uses" in err
    code, out, err = run(["scripts/nerva.py"], ["doctor", "--json"],
                         {"NERVA_ADMIN_TOKEN": NEW_VALUE, "JARVIS_ADMIN_TOKEN": OLD_VALUE})
    checks = {row["name"]: row for row in json.loads(out)["checks"]}
    assert code == 1 and checks["config_sources"]["status"] == "fail"
    assert checks["config_sources"]["reason"].startswith("env_spelling_conflict:JARVIS_ADMIN_TOKEN")
    assert NEW_VALUE not in out + err and OLD_VALUE not in out + err


def test_the_cli_entry_hands_everything_else_to_the_command_tree(clean, monkeypatch):
    from agents.cli import env_spelling, nerva

    seen = []
    monkeypatch.setattr(nerva, "main", lambda raw: seen.append(raw) or 0)
    assert env_spelling.main(["status", "--json"]) == 0 and seen == [["status", "--json"]]
    clean.setenv("NERVA_USER_TOKEN", "a-user-token-0001")
    clean.setenv("JARVIS_USER_TOKEN", "a-user-token-0002")
    assert env_spelling.main(["status"]) == nerva.EXIT_USAGE and len(seen) == 1
    assert env_spelling.main(["-p", "work", "doctor"]) == 0 and seen[-1] == ["-p", "work", "doctor"]


def test_the_operator_script_reads_the_admin_token_under_either_spelling_and_refuses_two(clean):
    from scripts import hermes_control

    clean.setenv("NERVA_ADMIN_TOKEN", "operator-token-1")
    assert hermes_control._admin_token() == "operator-token-1"
    clean.setenv("JARVIS_ADMIN_TOKEN", "operator-token-2")
    with pytest.raises(hermes_control.OperatorError) as refused:
        hermes_control._admin_token()
    assert "operator-token" not in str(refused.value)
    clean.delenv("NERVA_ADMIN_TOKEN")
    assert hermes_control._admin_token() == "operator-token-2"
