"""RB-2, after the adversarial review — what the fold did not reach.

The fold itself held (a ``.env`` value never beat a process value in 665 fresh-interpreter
permutations). What failed was around it, and each failure is pinned here on the real
mechanism:

B1  a ``${NERVA_X}`` reference expanded to nothing once the fold had moved ``NERVA_X``
    away, so ``NERVA_FILE_ROOTS=${NERVA_USER_HOME}/`` became ``/``. References are now
    resolved by the hub itself, under either spelling, identically in the real load and
    in the offline predictions; a path/endpoint/credential/allowlist built from a
    reference to nothing is refused, and so is a path-typed variable left at ``/``.
B2  one rule: a same-layer disagreement always refuses (there is no "NERVA wins" list);
    the process refusal says a launcher may own one of the two lines; the supervisor
    stops instead of respawning a coordinator that refused.
M1  a variable an operator *names* (``--token-env``, the MCP passthrough list, a
    ``${NAME}`` in a setting) resolves under either spelling.
m3  every entry point applies the rule, and the two kinds of reader cannot disagree.
m4  the getters' hot path builds no string.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
# agents.web freezes the tokens into module globals when first imported: import it now,
# before any test here has one in the environment (see test_rb2_env_alias.py).
import agents.web  # noqa: E402,F401
from agents.core import boot_guards, env_alias, env_config  # noqa: E402
from agents.core import env_provenance as ep  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def clean(monkeypatch):
    """No hub variable under either spelling and no marker; what a load adds is removed."""
    saved = dict(os.environ)
    for key in list(os.environ):
        if key == env_alias.MARKER or env_config.other_spelling(key):
            monkeypatch.delenv(key)
    yield monkeypatch
    for key in set(os.environ) - set(saved):
        os.environ.pop(key, None)


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    # only what an interpreter needs: nothing an earlier test's load left in this worker
    env = {key: value for key, value in os.environ.items()
           if key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR",
                      "VIRTUAL_ENV", "USER", "LOGNAME")}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", **extra})
    return env


# ── B1: references, in the real load ────────────────────────────────────────────────

ROOT_LINES = {
    "FILE_ROOTS": ("${%s_USER_HOME}/", "/srv/nerva/"),
    "TERMINAL_LOCAL_ROOTS": ("${%s_USER_HOME}/", "/srv/nerva/"),
    "MEDIA_ROOTS": ("${%s_USER_HOME}/media", "/srv/nerva/media"),
    "KEY_DIR": ("${%s_HOME}/keys", "/srv/data/keys"),
    "LOG_FILE": ("${%s_HOME}/logs/hub.log", "/srv/data/logs/hub.log"),
    "FORGET_ARCHIVE_DIR": ("${%s_HOME:-/safe}/forgotten", "/srv/data/forgotten"),
}


@pytest.mark.parametrize("process", ["NERVA", "JARVIS"])
@pytest.mark.parametrize("defined", ["NERVA", "JARVIS"])
@pytest.mark.parametrize("referenced", ["NERVA", "JARVIS"])
def test_a_reference_to_a_process_variable_resolves_under_either_spelling(clean, tmp_path, process, defined,
                                                                         referenced):
    """The reviewer's m3: the roots were ``/`` and the key directory ``/keys``."""
    clean.setenv(f"{process}_HOME", "/srv/data")
    clean.setenv(f"{process}_USER_HOME", "/srv/nerva")
    env_alias.normalize_process_env()
    repo = _write(tmp_path / ".env", "".join(f"{defined}_{name}={template % referenced}\n"
                                             for name, (template, _) in ROOT_LINES.items()))
    predicted = ep.after_repo_layer(repo, dict(os.environ))
    table = ep.load_layered_env(repo, None)
    for name, (_, expected) in ROOT_LINES.items():
        assert os.environ[f"JARVIS_{name}"] == expected, name
        assert predicted[f"JARVIS_{name}"] == expected, name                    # the prediction agrees
        assert ep.hub_value(f"NERVA_{name}", predicted) == expected
        assert table[f"JARVIS_{name}"]["layer"] == "repo_env" and f"NERVA_{name}" not in os.environ
    assert env_alias.root_paths() == []


@pytest.mark.parametrize("defined", ["NERVA", "JARVIS"])
@pytest.mark.parametrize("referenced", ["NERVA", "JARVIS"])
def test_a_reference_to_an_earlier_line_resolves_under_either_spelling(clean, tmp_path, defined, referenced):
    """m2 B13/B14: same-file ``${NERVA_KEY_DIR}`` worked and ``${JARVIS_KEY_DIR}`` was
    empty; across files it was the reverse. Now neither depends on the spelling."""
    same = _write(tmp_path / "same" / ".env",
                  f"{defined}_KEY_DIR=/k\n{defined}_EXEC_TEMP_DIR=${{{referenced}_KEY_DIR}}/t\n"
                  f"{defined}_FORGET_ARCHIVE_DIR=${{{referenced}_EXEC_TEMP_DIR}}/f\n"          # a chain
                  f"{defined}_LOG_FILE=${{{referenced}_NOPE_NOT_SET:-/var/log}}/hub.log\n")    # a default
    assert ep.after_repo_layer(same, {})["JARVIS_FORGET_ARCHIVE_DIR"] == "/k/t/f"
    ep.load_layered_env(same, None)
    assert os.environ["JARVIS_EXEC_TEMP_DIR"] == "/k/t" and os.environ["JARVIS_FORGET_ARCHIVE_DIR"] == "/k/t/f"
    assert os.environ["JARVIS_LOG_FILE"] == "/var/log/hub.log"
    for key in ("JARVIS_KEY_DIR", "JARVIS_EXEC_TEMP_DIR", "JARVIS_FORGET_ARCHIVE_DIR", "JARVIS_LOG_FILE"):
        os.environ.pop(key)
    os.environ.pop(env_alias.MARKER, None)
    repo = _write(tmp_path / "cross" / "repo.env", f"{defined}_KEY_DIR=/k\n")
    home = _write(tmp_path / "cross" / "home.env",
                  f"{defined}_EXEC_TEMP_DIR=${{{referenced}_KEY_DIR}}/t\nPLAIN_OTHER=${{{referenced}_KEY_DIR}}\n")
    derived = ep.derive(repo, home, {})
    ep.load_layered_env(repo, home)
    assert os.environ["JARVIS_EXEC_TEMP_DIR"] == "/k/t" and os.environ["PLAIN_OTHER"] == "/k"
    assert derived["JARVIS_EXEC_TEMP_DIR"]["layer"] == "user_env"


def test_the_environment_is_looked_up_before_the_files_earlier_lines(clean, tmp_path):
    """python-dotenv's order when it does not override, kept — and kept across spellings."""
    clean.setenv("NERVA_KEY_DIR", "/from-the-shell")
    env_alias.normalize_process_env()
    repo = _write(tmp_path / ".env", "JARVIS_KEY_DIR=/from-the-file\nNERVA_EXEC_TEMP_DIR=${JARVIS_KEY_DIR}/t\n"
                                     "PLAIN_A=one\nPLAIN_B=${PLAIN_A}-${PLAIN_MISSING}-${PLAIN_MISSING:-d}\n")
    ep.load_layered_env(repo, None)
    assert os.environ["JARVIS_KEY_DIR"] == "/from-the-shell" and os.environ["JARVIS_EXEC_TEMP_DIR"] == "/from-the-shell/t"
    assert os.environ["PLAIN_B"] == "one--d"              # not a hub variable: python-dotenv's result, as before


def test_the_load_and_every_prediction_use_one_function(clean, tmp_path):
    """They cannot disagree: the load no longer lets python-dotenv expand anything."""
    import inspect

    load_source = inspect.getsource(ep.load_layered_env)
    assert "load_dotenv" not in load_source and "layer_values(" in load_source
    for function in (ep.after_repo_layer, ep.hub_value, ep.derive_alias):
        source = inspect.getsource(function)
        assert "layer_values(" in source or "_layer_fold(" in source or "_folded_value(" in source
    assert "layer_values(" in inspect.getsource(ep._layer_fold)
    assert "_layer_fold(" in inspect.getsource(ep._folded_value)
    values = ep.layer_values((("NERVA_HOME", "/x"), ("A", "${JARVIS_HOME}/a"), ("B", "${NERVA_NOPE}/b"),
                              ("C", None), ("D", "${C}-${NERVA_HOME:-z}")), {"PATH": "/bin"})
    assert values.values == {"NERVA_HOME": "/x", "A": "/x/a", "B": "/b", "D": "-/x"}
    assert {key: [(ref.name, ref.state) for ref in refs] for key, refs in values.empty.items()} == {
        "B": [("NERVA_NOPE", ep.UNSET)], "D": [("C", ep.BLANK)]}


def test_every_hub_variable_that_names_a_path_is_on_the_list():
    """Measured: a hub name that looks like a directory or a file and is not on
    ``PATH_TYPED`` fails here, so the list cannot fall behind a new variable. The few
    names that only look like one are listed with what they really are."""
    import re

    looks_like_a_path = re.compile(r"(?:^|_)(?:ROOTS?|DIR|HOME|FILE|LOG|STATE|STORE|DEST|BUNDLE|PATH)(?:_|$)")
    not_a_path = {
        "FILE_MAX_BYTES", "FILE_TOOLS", "LOG_BACKUPS", "LOG_LEVEL", "LOG_MAX_MB", "LOG_REDACTION",   # sizes, switches
        "HOME_ASSISTANT",                 # a switch (the Home Assistant integration)
        "ROOT_PATH",                      # an ASGI URL prefix, where "/" is a meaning of its own
        "RESTORE_STAGE_TTL_HOURS", "RUNTIME_RESTORE_GRACE_SECONDS", "RUNTIME_RESTORE_POLL",
        "RESTORE_RUNTIME_WAIT_SECONDS",
    }
    candidates = {suffix for suffix in env_config.HUB_ENV_SUFFIXES if looks_like_a_path.search(suffix)}
    unlisted = sorted(candidates - env_alias.PATH_TYPED - not_a_path)
    assert not unlisted, f"{unlisted}: path-typed hub variables missing from env_alias.PATH_TYPED"
    assert env_alias.PATH_TYPED - {"TERMINAL_SSH_KNOWN_HOSTS"} <= env_config.HUB_ENV_SUFFIXES
    assert not (not_a_path & env_alias.PATH_TYPED) and not_a_path <= env_config.HUB_ENV_SUFFIXES
    for suffix in env_alias.PATH_TYPED:
        assert env_alias.path_typed("NERVA_" + suffix) and env_alias.path_typed("JARVIS_" + suffix)
    # by name, never by a substring: these only LOOK like paths, endpoints or files
    for name in ("JARVIS_HOME_ASSISTANT", "JARVIS_FILE_TOOLS", "JARVIS_FILE_MAX_BYTES", "JARVIS_PLAYWRIGHT_HOST",
                 "JARVIS_DESKTOP_HOST", "JARVIS_HOST", "JARVIS_HA_URL", "JARVIS_LOG_LEVEL", "NERVA_HUB_URL", "PATH"):
        assert not env_alias.path_typed(name), name
    assert not hasattr(env_alias, "reference_sensitive") and not hasattr(env_alias, "refuse_unsafe_paths")


# ── B2: one rule, a truthful refusal, a supervisor that stops ───────────────────────

def test_the_process_refusal_says_a_launcher_may_own_one_of_the_two_lines():
    env = {"NERVA_HOME": "/somewhere-secret-71", "JARVIS_HOME": "/data"}
    message = env_alias.conflict_message(env_alias.conflicts(env))
    assert "NERVA_HOME / JARVIS_HOME" in message
    for phrase in ("container image", "compose file", "service unit", "start scripts",
                   "under the SAME spelling the launcher uses", "docs/FLAGS.md"):
        assert phrase in message, phrase
    assert "/somewhere-secret-71" not in message and "/data" not in message
    in_file = env_alias.conflict_message(["JARVIS_HOME"], "the repo .env")
    assert "launcher" not in in_file and "Keep one of the two lines in that file" in in_file
    with pytest.raises(env_alias.ConfigurationRefused) as refused:
        env_alias.refuse_conflicts(env)
    assert isinstance(refused.value, SystemExit) and str(refused.value) == message


def test_the_launcher_scripts_never_turn_a_new_spelling_into_a_conflict(tmp_path):
    """start.sh's own defaulting lines, run in a real shell: a NERVA_ value the user set
    is left alone, and with nothing set the default is what it always was."""
    lines = [line for line in (ROOT / "start.sh").read_text(encoding="utf-8").splitlines()
             if not line.lstrip().startswith("#") and ("JARVIS_HUD=" in line or line.startswith("PORT="))]
    assert len(lines) == 2
    script = "\n".join(lines) + '\necho "HUD=${JARVIS_HUD-unset} NEW=${NERVA_HUD-unset} PORT=$PORT"\n'

    def run(extra):
        out = subprocess.run(["bash", "-c", script], env={"PATH": os.environ["PATH"], **extra},
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    assert run({}) == "HUD=v2 NEW=unset PORT=8080"
    assert run({"NERVA_HUD": "v1", "NERVA_PORT": "9001"}) == "HUD=unset NEW=v1 PORT=9001"
    assert run({"JARVIS_HUD": "v1", "JARVIS_PORT": "9002"}) == "HUD=v1 NEW=unset PORT=9002"
    signal = [line for line in (ROOT / "start.sh").read_text(encoding="utf-8").splitlines()
              if "JARVIS_SIGNAL_LAYER" in line and not line.lstrip().startswith(("#", "echo"))]
    assert all("NERVA_SIGNAL_LAYER" in line for line in signal) and len(signal) == 2
    config = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import {loadConfig} from './services/signal-layer/src/config.mjs';"
         "console.log([loadConfig({NERVA_SIGNAL_LAYER_MODE:'live'}).mode,"
         "loadConfig({JARVIS_SIGNAL_LAYER_MODE:'live'}).mode, loadConfig({}).mode].join(','))"],
        cwd=ROOT, capture_output=True, text=True, timeout=60) if _has("node") else None
    if config is not None:
        assert config.stdout.strip() == "live,live,replay", config.stderr


def _has(program: str) -> bool:
    import shutil

    return shutil.which(program) is not None


def test_the_supervisor_stops_on_a_refused_configuration_instead_of_respawning(tmp_path):
    """The reviewer saw five refusals in twelve seconds. The coordinator now leaves with
    the configuration status, and the supervisor stops, once, with the same status."""
    from scripts import runtime_supervisor

    assert runtime_supervisor.CONFIG_REFUSED_EXIT == env_alias.CONFIG_REFUSED_EXIT == 78
    log = tmp_path / "runtime.jsonl"
    env = _child_env({"JARVIS_HOME": str(tmp_path / "data"), "JARVIS_RUNTIME_LOG": str(log),
                      "JARVIS_RUNTIME_RESPAWN_DELAY": "0.05", "JARVIS_RUNTIME_FAKE_LLM": "1",
                      "NERVA_ADMIN_TOKEN": "one-token-aa11bb", "JARVIS_ADMIN_TOKEN": "another-token-cc22dd"})
    out = subprocess.run([sys.executable, "scripts/runtime_supervisor.py"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 78, (out.returncode, out.stderr[-1500:])      # a PROCESS pair: permanent
    assert out.stderr.count("Refusing to start: NERVA_ADMIN_TOKEN / JARVIS_ADMIN_TOKEN") == 1     # once
    assert "not respawning" in out.stderr
    assert "one-token-aa11bb" not in out.stdout + out.stderr and "another-token-cc22dd" not in out.stdout + out.stderr
    events = [json.loads(line)["supervisor_event"] for line in log.read_text(encoding="utf-8").splitlines()
              if '"supervisor_event"' in line]
    assert events.count("spawned") == 1 and "respawned" not in events and "config_refused" in events
    unit = (ROOT / "deploy/systemd/jarvis-runtime.service").read_text(encoding="utf-8")
    assert "RestartPreventExitStatus=78" in unit


# ── M1: a variable the operator names ───────────────────────────────────────────────

def test_token_env_names_the_variable_under_either_spelling(clean, monkeypatch):
    from scripts import nerva_mcp_stdio

    captured = {}

    class _Transport:
        def __init__(self, url, headers, **kwargs):
            captured["headers"] = dict(headers)

    monkeypatch.setattr(nerva_mcp_stdio, "StreamableHttpTransport", _Transport)
    monkeypatch.setattr(nerva_mcp_stdio.asyncio, "run", lambda coroutine: coroutine.close())
    clean.setenv("NERVA_USER_TOKEN", "stdio-user-token-5a5a")
    env_alias.normalize_process_env()
    for named in ("NERVA_USER_TOKEN", "JARVIS_USER_TOKEN"):
        captured.clear()
        assert nerva_mcp_stdio.main(["--token-env", named]) == 0
        assert "stdio-user-token-5a5a" in json.dumps(captured["headers"]), named
    captured.clear()
    assert nerva_mcp_stdio.main([]) == 0 and "stdio-user-token-5a5a" in json.dumps(captured["headers"])


def test_the_stdio_bridge_refuses_a_variable_set_twice(tmp_path):
    """m3: it read the JARVIS_ value and went on. Every entry point applies the rule."""
    env = _child_env({"NERVA_USER_TOKEN": "a-user-token-0101", "JARVIS_USER_TOKEN": "a-user-token-0202"})
    out = subprocess.run([sys.executable, "scripts/nerva_mcp_stdio.py"], cwd=ROOT, env=env, input="",
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 2 and "NERVA_USER_TOKEN / JARVIS_USER_TOKEN" in out.stderr
    assert "bridging stdio" not in out.stderr
    assert "a-user-token-0101" not in out.stderr and "a-user-token-0202" not in out.stderr


def test_the_mcp_passthrough_list_gives_the_child_what_the_old_spelling_gives(clean):
    from agents.core.mcp.client import stdio_env_baseline, stdio_env_extra_allowed

    host = {"PATH": "/usr/bin", "JARVIS_HOME": "/data", "JARVIS_PROFILE": "work", "JARVIS_ADMIN_TOKEN": "t-0f0f0f",
            "JARVIS_PORT": "8080", "OPENAI_API_KEY": "sk-zz"}
    old = stdio_env_baseline({**host, "JARVIS_MCP_STDIO_ALLOWED_ENV": "JARVIS_HOME,JARVIS_PROFILE"})
    for declared in ("NERVA_HOME,NERVA_PROFILE", "nerva_home, JARVIS_PROFILE"):
        for flag in ("JARVIS_MCP_STDIO_ALLOWED_ENV", "NERVA_MCP_STDIO_ALLOWED_ENV"):
            assert stdio_env_baseline({**host, flag: declared}) == old, (flag, declared)
    assert old["JARVIS_HOME"] == "/data" and old["JARVIS_PROFILE"] == "work"
    assert not [key for key in old if key.startswith("NERVA_") or "TOKEN" in key or key == "JARVIS_PORT"]
    # a mapping still spelled the new way hands the same keys over, and nothing more
    raw = {"PATH": "/usr/bin", "NERVA_HOME": "/data", "NERVA_PROFILE": "work", "NERVA_ADMIN_TOKEN": "t-0f0f0f",
           "NERVA_MCP_STDIO_ALLOWED_ENV": "NERVA_HOME,NERVA_PROFILE"}
    assert stdio_env_baseline(raw) == old
    clean.setenv("NERVA_MCP_STDIO_ALLOWED_ENV", "NERVA_HOME")
    assert stdio_env_extra_allowed() == frozenset({"JARVIS_HOME"})


def test_a_setting_may_name_a_hub_variable_under_either_spelling(clean):
    from agents.core import settings_interpolation as si

    clean.setenv("NERVA_HA_URL", "http://ha.local:8123")
    clean.setenv("NERVA_ADMIN_TOKEN", "admin-token-for-refusal")
    env_alias.normalize_process_env()
    for reference in ("${NERVA_HA_URL}", "${env:NERVA_HA_URL}", "${JARVIS_HA_URL}", "${env:JARVIS_HA_URL}"):
        assert si.expand(reference, setting="integrations.home_assistant_url") == "http://ha.local:8123", reference
    assert si.expand("x${NERVA_HA_URL}/y", setting="a.b") == "xhttp://ha.local:8123/y"
    rows = si.references("${NERVA_HA_URL} ${JARVIS_HA_URL} ${NERVA_NOT_SET_ANYWHERE}")
    assert rows == [{"name": "JARVIS_HA_URL", "set": True}, {"name": "NERVA_NOT_SET_ANYWHERE", "set": False}]
    # the hub's own credentials stay unnameable, under either spelling
    for reference in ("${NERVA_ADMIN_TOKEN}", "${JARVIS_ADMIN_TOKEN}"):
        refuse = lambda name, value: si.refusal(name, credential_setting=True)   # noqa: E731
        assert si.expand(reference, setting="a.b", refuse=refuse) == reference
        assert si.references(reference, refuse=refuse)[0]["refused"] == si.HUB_CREDENTIAL


# ── m3 / m4 / NIT ─────────────────────────────────────────────────────────────────

def test_a_getter_and_a_direct_reader_never_disagree(clean):
    """In a process that holds a refused pair (it has not stopped yet, or never loads),
    ``env_config`` answers what ``os.environ[JARVIS_X]`` answers."""
    for name, new, old in (("HARDENED", "0", "1"), ("HARDENED", "1", "0"), ("PORT", "9000", "8080"),
                           ("ADMIN_TOKEN", "n-token", "j-token"), ("HOST", "0.0.0.0", "127.0.0.1")):
        clean.setenv(f"NERVA_{name}", new)
        clean.setenv(f"JARVIS_{name}", old)
        assert env_config.env_str(f"JARVIS_{name}") == os.environ[f"JARVIS_{name}"] == old
        assert env_config.env_str(f"NERVA_{name}") == old
        assert env_alias.conflicts() == [f"JARVIS_{name}"]
        clean.delenv(f"NERVA_{name}")
        clean.delenv(f"JARVIS_{name}")
    clean.setenv("NERVA_HARDENED", "1")                     # one spelling, no fold: the getter still sees it
    assert env_config.env_flag("JARVIS_HARDENED") is True


def test_every_entry_point_refuses_a_variable_set_twice(tmp_path):
    """Process-level, in a fresh interpreter each: the hub's load (serve.py, the lifespan,
    agents.run, the coordinator all go through it), the boot guards, both CLI entries,
    the stdio bridge and the operator script."""
    pair = {"NERVA_ADMIN_TOKEN": "tok-n-000111", "JARVIS_ADMIN_TOKEN": "tok-j-222333",
            "JARVIS_HOME": str(tmp_path / "data"), "NERVA_HUB_URL": "http://127.0.0.1:9"}
    commands = {
        "load_hub_env": ["-c", "from agents.core.env_provenance import load_hub_env; load_hub_env()"],
        "boot guards": ["-c", "from agents.core.boot_guards import enforce_boot_posture; enforce_boot_posture()"],
        "coordinator": ["scripts/coordinator.py"],
        "nerva": ["scripts/nerva.py", "status"],
        "python -m agents.cli": ["-m", "agents.cli", "status"],
        "stdio bridge": ["scripts/nerva_mcp_stdio.py"],
        "hermes_control": ["scripts/hermes_control.py", "status"],
    }
    for label, argv in commands.items():
        out = subprocess.run([sys.executable, *argv], cwd=ROOT, env=_child_env(pair), input="",
                             capture_output=True, text=True, timeout=180)
        said = out.stdout + out.stderr
        assert out.returncode != 0, label
        assert "NERVA_ADMIN_TOKEN" in said and "JARVIS_ADMIN_TOKEN" in said, (label, said[-600:])
        assert "tok-n-000111" not in said and "tok-j-222333" not in said, label
    coordinator = subprocess.run([sys.executable, "scripts/coordinator.py"], cwd=ROOT, env=_child_env(pair),
                                 capture_output=True, text=True, timeout=180)
    assert coordinator.returncode == env_alias.CONFIG_REFUSED_EXIT


def test_an_inherited_spelling_marker_is_discarded_and_the_fold_still_runs(tmp_path):
    """NIT: the marker is this process's own note. One handed in from outside claims
    nothing — and a forked child keeps its parent's, being the same image."""
    probe = ("import json, os\nimport agents.core\nfrom agents.core import env_alias\nimport core.env_alias\n"
             "core.env_alias.normalize_process_env()\n"
             "print(json.dumps({'marker': os.environ.get(env_alias.MARKER),"
             " 'port': env_alias.spelling_info('JARVIS_PORT')['deprecated'],"
             " 'host': env_alias.spelling_info('JARVIS_HOST')['deprecated']}))\n")
    env = _child_env({env_alias.MARKER: "JARVIS_PORT,JARVIS_ADMIN_TOKEN", "JARVIS_PORT": "8080",
                      "NERVA_HOST": "127.0.0.1"})
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'agents')\n" + probe], cwd=ROOT,
                         env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-1500:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"marker": "JARVIS_HOST", "port": True, "host": False}


def test_the_hub_name_check_is_a_lookup_and_the_getter_builds_no_string(clean, monkeypatch):
    """m4. Structure, then a count: the name check is one dictionary lookup, the getter's
    own code builds no string, a hub variable costs exactly two reads of the environment
    and a name with one spelling exactly one, as before RB-2. (Timings are in the report;
    a wall-clock bound does not belong in a suite that runs eight workers wide.)"""
    import dis

    assert env_config._OTHER["JARVIS_HARDENED"] == "NERVA_HARDENED" and env_config._OTHER["NERVA_PORT"] == "JARVIS_PORT"
    assert len(env_config._OTHER) == 2 * len(env_config.HUB_ENV_SUFFIXES)
    built = {instruction.opname for instruction in dis.get_instructions(env_config._read)}
    assert not built & {"BINARY_SLICE", "BUILD_STRING", "FORMAT_VALUE", "BINARY_SUBSCR", "BINARY_OP"}
    clean.setenv("JARVIS_HARDENED", "1")
    reads = []
    original = os._Environ.__getitem__

    def spy(self, key):
        reads.append(key)
        return original(self, key)

    monkeypatch.setattr(os._Environ, "__getitem__", spy)
    for name, expected in (("JARVIS_HARDENED", ["JARVIS_HARDENED", "NERVA_HARDENED"]),
                           ("NERVA_HARDENED", ["NERVA_HARDENED", "JARVIS_HARDENED"]),
                           ("JARVIS_ROLE_VISION_MODEL", ["JARVIS_ROLE_VISION_MODEL", "NERVA_ROLE_VISION_MODEL"]),
                           ("DEV_MODE", ["DEV_MODE"]), ("NERVA_HUB_URL", ["NERVA_HUB_URL"]),
                           ("OPENAI_API_KEY", ["OPENAI_API_KEY"]), ("JARVIS_NOT_A_HUB_NAME", ["JARVIS_NOT_A_HUB_NAME"])):
        reads.clear()
        env_config.env_str(name)
        assert reads == expected, name


# ── the reviewer's permutation matrix, kept ─────────────────────────────────────────

def _scenario(tmp_path: Path, number: int, process: dict[str, str], repo: str | None, home: str | None,
              name: str) -> dict:
    """One scenario of the reviewer's matrix.py, on the real fold and the real load: a
    process environment, a repo .env and a data-home .env -> what the hub then holds."""
    for key in list(os.environ):
        if key == env_alias.MARKER or env_config.other_spelling(key):
            del os.environ[key]
    os.environ.update(process)
    try:
        env_alias.normalize_process_env()                 # what importing the package does
        ep.load_layered_env(_write(tmp_path / f"{number}-repo.env", repo) if repo is not None else None,
                            _write(tmp_path / f"{number}-home.env", home) if home is not None else None)
    except SystemExit:
        return {"refused": True}
    return {"J": os.environ.get(f"JARVIS_{name}"), "N": os.environ.get(f"NERVA_{name}"),
            "getter": env_config.env_str(f"JARVIS_{name}", "<unset>")}


def test_the_reviewers_permutation_matrix_holds(clean, tmp_path):
    """635 permutations (matrix.py A, m4.py C and D): a process value under either
    spelling is never changed by a file under either spelling, in either or both layers,
    whatever the file's value; the first file beats the second the same way; and one
    layer setting both spellings resolves by the one rule — equal or blank is fine,
    different is refused. The reviewer ran these in fresh interpreters; here they run on
    the same functions in one process, so they stay in the suite."""
    import itertools

    values = ["1", "0", "", " ", "maybe"]
    count = itertools.count()
    violations = []
    for name in ("HARDENED", "STRICT_EGRESS", "SAFE_MODE", "ADMIN_TOKEN", "TRUSTED_PROXIES"):
        for in_process, in_file, value, layer in itertools.product(
                ("JARVIS_", "NERVA_"), ("JARVIS_", "NERVA_", "both"), values, ("repo", "home", "both")):
            text = (f"JARVIS_{name}={value}\nNERVA_{name}={value}\n" if in_file == "both"
                    else f"{in_file}{name}={value}\n")
            got = _scenario(tmp_path, next(count), {in_process + name: "1"},
                            text if layer in ("repo", "both") else None,
                            text if layer in ("home", "both") else None, name)
            if got != {"J": "1", "N": None, "getter": "1"}:
                violations.append(("A", name, in_process, in_file, value, layer, got))
    for name in ("HARDENED", "ADMIN_TOKEN"):
        for in_repo, in_home, value in itertools.product(("JARVIS_", "NERVA_"), ("JARVIS_", "NERVA_", "both"), values):
            home = (f"JARVIS_{name}={value}\nNERVA_{name}={value}\n" if in_home == "both"
                    else f"{in_home}{name}={value}\n")
            got = _scenario(tmp_path, next(count), {}, f"{in_repo}{name}=1\n", home, name)
            if got.get("J") != "1" or got.get("N") is not None:
                violations.append(("C", name, in_repo, in_home, value, got))
    for where, (new, old), flipped in itertools.product(("process", "repo", "home"),
                                                        itertools.product(values, values), (False, True)):
        pairs = [("NERVA_HARDENED", new), ("JARVIS_HARDENED", old)]
        if flipped:
            if where == "process":
                continue
            pairs.reverse()
        text = "".join(f"{key}='{value}'\n" for key, value in pairs)
        got = _scenario(tmp_path, next(count), dict(pairs) if where == "process" else {},
                        text if where == "repo" else None, text if where == "home" else None, "HARDENED")
        if new == old or not new.strip() or not old.strip():
            want = new if new == old else (old if not new.strip() and old.strip() else new)
            if got != {"J": want, "N": None, "getter": want}:
                violations.append(("D", where, new, old, flipped, got))
        elif got != {"refused": True}:
            violations.append(("D not refused", where, new, old, flipped, got))
    assert next(count) == 635 and violations == []
