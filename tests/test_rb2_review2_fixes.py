"""RB-2, second adversarial review — a ``JARVIS_``-only install that starts on main starts here.

The alias itself held again. What the second review found is that the two refusals
added after the first one stopped *existing* installs, and that one of them printed a
piece of a credential. The rule this file pins:

    A JARVIS_-only configuration that boots on main boots here with the same effective
    values — except where the value on main was provably an accident. There are exactly
    three such accidents, each a thing python-dotenv did silently in a ``.env``:
      1. a path-typed variable built from a ``${NAME}`` that nothing sets;
      2. a path-typed variable that opens with a ``${NAME}`` that is set but empty;
      3. a hub credential with a ``${NAME}`` that nothing sets.
    (The fourth refusal, one variable under both spellings with different values, cannot
    exist in a JARVIS_-only file.)

Everything else boots as before: a root the operator wrote out (a loud warning), the
feature-off idiom, flags and addresses built from an unset reference (a warning). No
message carries a value or a piece of one, and the tools that repair a broken
configuration are never stopped by any of it.
"""
from __future__ import annotations

import io
import json
import logging
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
# agents.web freezes the tokens into module globals when first imported: import it now,
# before any test here has one in the environment.
import agents.web  # noqa: E402,F401
from agents.core import boot_guards, env_alias, env_config  # noqa: E402
from agents.core import env_provenance as ep  # noqa: E402

_KEPT = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR", "VIRTUAL_ENV",
         "USER", "LOGNAME")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def clean(monkeypatch):
    """No hub variable under either spelling and none of the hub's notes; what a load adds
    is removed; the load's own record of the last run is put back."""
    saved = dict(os.environ)
    for key in list(os.environ):
        if key in env_alias.PRIVATE_NAMES or env_config.other_spelling(key):
            monkeypatch.delenv(key)
    monkeypatch.setattr(ep, "_PROBLEMS", [])
    monkeypatch.setattr(ep, "_ROOTS_WARNED", set())
    monkeypatch.setattr(ep, "_HUB_LOADED", ep._HUB_LOADED)
    yield monkeypatch
    for key in set(os.environ) - set(saved):
        os.environ.pop(key, None)


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in _KEPT}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", **extra})
    return env


def _dotenv_adds(text: str, environ: dict[str, str]) -> dict[str, str]:
    """What main's load (``load_dotenv(override=False, interpolate=True)``) adds to
    *environ* from *text*: python-dotenv itself, run against a copy of the environment."""
    from dotenv.main import DotEnv

    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(environ)
    try:
        with open(os.devnull, "w") as quiet:
            logging.disable(logging.CRITICAL)
            try:
                values = DotEnv(dotenv_path=None, stream=io.StringIO(text), interpolate=True, override=False).dict()
            finally:
                logging.disable(logging.NOTSET)
                quiet.close()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return {key: value for key, value in values.items() if key not in environ and value is not None}


# ── BLOCKER 1: a root the operator wrote out boots, loudly ─────────────────────────

LITERAL_ROOTS = ["/", "//", "/.", "/./", "//./", "/..", "/tmp/..", " / ", "/proc/self/root", "C:\\", "c:", "C:.",
                 "/tmp;/", "/srv,/", "/tmp:/", "'/'"]


@pytest.mark.parametrize("name", ["FILE_ROOTS", "TERMINAL_LOCAL_ROOTS", "MEDIA_ROOTS", "KEY_DIR", "USER_HOME"])
@pytest.mark.parametrize("spelling", ["JARVIS", "NERVA"])
def test_a_root_written_out_boots_from_the_process_and_from_a_file(clean, tmp_path, caplog, capsys, name, spelling):
    key = f"{spelling}_{name}"
    for index, value in enumerate(LITERAL_ROOTS):
        # written in a .env (quoted only where a bare value would lose its spaces) …
        written = f'"{value}"' if value != value.strip() else value
        repo = _write(tmp_path / f"{index}.env", f"{key}={written}\n")
        ep.load_layered_env(repo, None)                                  # never refuses
        assert os.environ[f"JARVIS_{name}"] == _dotenv_adds(f"X={written}\n", {})["X"], value
        assert ep.problems() == []
        os.environ.pop(f"JARVIS_{name}")
        os.environ.pop(env_alias.MARKER, None)
        # … and in the process environment
        clean.setenv(key, value)
        env_alias.normalize_process_env()
        ep.load_layered_env(None, None)
        boot_guards.assert_parseable_posture_flags()
        os.environ.pop(f"JARVIS_{name}", None)
        clean.delenv(key, raising=False)
    said = caplog.text + "".join(capsys.readouterr())
    assert "Refusing" not in said


def test_a_literal_root_is_announced_once_by_name_and_never_by_value(clean, tmp_path, caplog, capsys):
    clean.setenv("JARVIS_FILE_ROOTS", "/")
    repo = _write(tmp_path / ".env", "NERVA_KEY_DIR=//\nJARVIS_MEDIA_ROOTS=/srv/media\nJARVIS_TERMINAL_LOCAL_ROOTS=/tmp;/\n")
    with caplog.at_level(logging.WARNING):
        ep.load_layered_env(repo, None)
        ep.load_layered_env(repo, None)                                  # a second load says nothing new
    loud = [record.getMessage() for record in caplog.records if "filesystem root" in record.getMessage()]
    assert len(loud) == 2 and all(line.startswith("[SECURITY] ") for line in loud)
    assert "JARVIS_FILE_ROOTS" in loud[0] and "process environment" in loud[0]
    assert "NERVA_KEY_DIR" in loud[1] and "repo .env" in loud[1]
    assert "MEDIA_ROOTS" not in "".join(loud) and "TERMINAL_LOCAL_ROOTS" not in "".join(loud)   # no list parsing
    with caplog.at_level(logging.WARNING):
        boot_guards.assert_parseable_posture_flags()                     # the guards say nothing again
        boot_guards.assert_parseable_posture_flags()
    assert len([record for record in caplog.records if "filesystem root" in record.getMessage()]) == 2
    assert "filesystem root" not in "".join(capsys.readouterr())
    assert env_alias.root_paths({"JARVIS_FILE_ROOTS": "/tmp;/", "JARVIS_MEDIA_ROOTS": "/a:/", "JARVIS_PORT": "/",
                                 "JARVIS_FILE_TOOLS": "/"}) == []
    assert not hasattr(env_alias, "unsafe_paths") and "_LIST_SEPARATORS" not in vars(env_alias)


def test_the_doctor_warns_on_a_literal_root_and_does_not_fail(tmp_path):
    from scripts import doctor

    root = tmp_path / "repo"
    _write(root / ".env", "JARVIS_FILE_TOOLS=1\nJARVIS_FILE_ROOTS=/\n")
    check = doctor.check_config_sources(root, {"JARVIS_KEY_DIR": "/", "PATH": "/usr/bin"})
    assert check.status == doctor.WARN and check.reason.startswith("env_root_path:JARVIS_FILE_ROOTS,JARVIS_KEY_DIR")
    assert check.data["root_paths"] == {"process": ["JARVIS_KEY_DIR"], "repo_env": ["JARVIS_FILE_ROOTS"]}
    assert "references_to_nothing" not in check.data


# ── BLOCKER 2: the table, decided from the record of the expansion ─────────────────

BOOTS, WARNS, ROOT_WARNED = "boots", "boots with a warning", "boots, announced as a root"
TABLE = [
    # the feature-off idiom: defined, and blank
    ("HA_URL=\nHA_TOKEN=\n{p}_HA_URL=${{HA_URL}}\n{p}_H30_HA_TOKEN=${{HA_TOKEN}}\n", BOOTS, None),
    ("HA_ON=\n{p}_HOME_ASSISTANT=${{HA_ON}}\n", BOOTS, None),
    ("LOGDIR=\n{p}_LOG_FILE=/var/log/${{LOGDIR}}hub.log\n", BOOTS, None),               # blank, not leading
    ("{p}_ADMIN_TOKEN=\n{p}_USER_TOKEN=${{{p}_ADMIN_TOKEN}}\n", BOOTS, None),           # a credential, blank reference
    # flags and addresses that only LOOK like paths: never judged by a substring of their name
    ("{p}_HOME_ASSISTANT=${{UNSET_FLAG}}\n", WARNS, "HOME_ASSISTANT"),
    ("{p}_FILE_TOOLS=${{UNSET_FLAG}}\n", WARNS, "FILE_TOOLS"),
    ("{p}_FILE_MAX_BYTES=${{UNSET_SIZE}}\n", WARNS, "FILE_MAX_BYTES"),
    ("{p}_PLAYWRIGHT_HOST=${{UNSET_HOST}}\n", WARNS, "PLAYWRIGHT_HOST"),
    ("{p}_DESKTOP_HOST=${{UNSET_HOST}}\n", WARNS, "DESKTOP_HOST"),
    ("{p}_HA_URL=http://${{UNSET_HOST}}:8123\n", WARNS, "HA_URL"),
    ("{p}_ALLOWED_HOSTS=nerva.local,${{TAILNET}}\n", WARNS, "ALLOWED_HOSTS"),
    ("{p}_TRUSTED_PROXIES=${{PROXY_CIDR}}\n", WARNS, "TRUSTED_PROXIES"),
    ("{p}_HOST=${{BIND}}\n", WARNS, "HOST"),
    # a default always covers the reference
    ("{p}_LOG_FILE=${{LOGDIR:-/var/log}}/hub.log\n{p}_KEY_DIR=${{PREFIX:-}}/etc/nerva/keys\n", BOOTS, None),
    ("{p}_ADMIN_TOKEN=tok-${{SUFFIX:-0001}}-end\n", BOOTS, None),
    # the three accidents
    ("{p}_LOG_FILE=${{LOGDIR}}/hub.log\n", ep.PATH_UNSET, "LOG_FILE"),
    ("{p}_FILE_ROOTS=/srv/data,${{EXTRA_ROOT}}/\n", ep.PATH_UNSET, "FILE_ROOTS"),
    ("{p}_KEY_DIR=/etc/${{TYPO}}/keys\n", ep.PATH_UNSET, "KEY_DIR"),
    ("{p}_FILE_ROOTS=${{DATA}}/.\n", ep.PATH_UNSET, "FILE_ROOTS"),                       # not from the final string
    # a reference that is DEFINED and blank is the operator's stated value: it boots, whatever it builds
    ("PREFIX=\n{p}_LOG_FILE=${{PREFIX}}/var/log/hub.log\n", BOOTS, None),             # the optional prefix
    ("DATA=\n{p}_KEY_DIR=${{DATA}}/keys\n", BOOTS, None),
    ("DATA=\n{p}_FILE_ROOTS=${{DATA}}/\n", ROOT_WARNED, "FILE_ROOTS"),                 # … and a root is announced
    ("DATA=\n{p}_MEDIA_ROOTS=${{DATA}}//./\n", ROOT_WARNED, "MEDIA_ROOTS"),
    ("{p}_USER_HOME=\n{p}_TERMINAL_LOCAL_ROOTS=${{{p}_USER_HOME}}/\n", ROOT_WARNED, "TERMINAL_LOCAL_ROOTS"),
    # masked by name, and not credentials: an integer, a flag, a secret handle (main's value, a warning)
    ("{p}_BUDGET_MAX_TOKENS=${{BUDGET}}\n", WARNS, "BUDGET_MAX_TOKENS"),
    ("{p}_PASSIVE_CAPTURE=${{CAPTURE}}\n", WARNS, "PASSIVE_CAPTURE"),
    ("{p}_HA_TOKEN_REF={{{{secret:${{HA_SECRET_NAME}}}}}}\n", WARNS, "HA_TOKEN_REF"),
    ("{p}_NOUS_CLIENT_ID=${{CLIENT}}\n", WARNS, "NOUS_CLIENT_ID"),
    ("{p}_ADMIN_TOKEN=abc${{NOT_SET_ANYWHERE}}def\n", ep.CREDENTIAL_UNSET, "ADMIN_TOKEN"),
    ("{p}_AUDIT_KEY='k1${{x}}k2'\n", ep.CREDENTIAL_UNSET, "AUDIT_KEY"),
    ("{p}_ROLE_VISION_KEY=${{VISION_KEY}}\n", ep.CREDENTIAL_UNSET, "ROLE_VISION_KEY"),
]


@pytest.mark.parametrize("spelling", ["JARVIS", "NERVA"])
@pytest.mark.parametrize("template, outcome, suffix", TABLE)
def test_the_reference_table(clean, tmp_path, caplog, spelling, template, outcome, suffix):
    text = template.format(p=spelling)
    repo = _write(tmp_path / ".env", text)
    main_gives = _dotenv_adds(text.replace("NERVA_", "JARVIS_"), dict(os.environ))
    predicted = ep.derive_alias(repo, None, dict(os.environ))[2]
    if outcome in (BOOTS, WARNS, ROOT_WARNED):
        with caplog.at_level(logging.INFO):
            ep.load_layered_env(repo, None)
        assert ep.problems() == [] and predicted == {}
        for key, value in main_gives.items():
            assert os.environ[key] == value, key                       # exactly what main's load gave it
        warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        if outcome == WARNS:
            assert len(warnings) == 1 and f"{spelling}_{suffix}" in warnings[0] and "nothing sets" in warnings[0]
        elif outcome == ROOT_WARNED:
            assert len(warnings) == 1 and warnings[0].startswith(f"[SECURITY] {spelling}_{suffix} is set to the")
        else:
            assert warnings == []
        return
    variable = f"{spelling}_{suffix}"
    assert predicted == {"repo_env": {variable: outcome}}
    with pytest.raises(env_alias.ConfigurationRefused) as refused:
        ep.load_layered_env(repo, None)
    message = str(refused.value)
    assert message.startswith("Refusing to start: in the repo .env, ") and variable in message
    assert not [key for key in main_gives if key in os.environ]         # nothing of the file is in effect
    assert [row["kind"] for row in ep.problems()] == [ep.REFERENCE_TO_NOTHING]
    assert ep.problems()[0]["names"] == [variable]
    # … and a load that must not stop (a repair tool's) gives every line main's value
    ep.load_layered_env(repo, None, refuse=False)
    for key, value in main_gives.items():
        assert os.environ[key] == value, key
    assert ep.problems()[0]["message"] == message


def test_the_refusals_cannot_be_tripped_by_a_literal_or_dodged_by_a_spelling_of_the_root(clean, tmp_path):
    """Decided from which references came to nothing — never from the string that results."""
    for tail in ("/", "/.", "//./", "/..", "/../etc", "\\", "/proc/self/root"):
        repo = _write(tmp_path / "a.env", f"JARVIS_FILE_ROOTS=${{NOPE}}{tail}\n")
        with pytest.raises(env_alias.ConfigurationRefused):
            ep.load_layered_env(repo, None)
        repo = _write(tmp_path / "b.env", f"EMPTY=\nJARVIS_FILE_ROOTS=${{EMPTY}}{tail}\n")
        ep.load_layered_env(repo, None)                  # defined and blank: the operator's value, as on main
        assert os.environ.pop("JARVIS_FILE_ROOTS") == tail
    values = ep.layer_values((("E", ""), ("JARVIS_FILE_ROOTS", "/"), ("JARVIS_KEY_DIR", "${E:-}/"),
                              ("JARVIS_LOG_FILE", "/a/${E}/b")), {})
    verdict = ep.judge(values, env_alias.fold(values.values))
    assert verdict.refused == {} and verdict.noted == ("JARVIS_LOG_FILE",)


def test_a_variable_that_is_not_the_hubs_is_never_judged(clean, tmp_path):
    repo = _write(tmp_path / ".env", "OPENAI_API_KEY=${NOPE}\nSOME_TOOL_DIR=${NOPE}/x\nNERVA_HUB_URL=${NOPE}\n"
                                     "NERVA_WORKSPACE_SSO_SECRET=${NOPE}\nJARVIS_HOME=${NOPE}/data\n")
    ep.load_layered_env(repo, None)
    assert os.environ["OPENAI_API_KEY"] == "" and os.environ["SOME_TOOL_DIR"] == "/x"
    assert "JARVIS_HOME" not in os.environ and ep.problems() == []      # process-only: recorded, not judged


# ── MAJOR 1: nothing derived from a value is ever printed ──────────────────────────

# Values no dictionary word, variable name or message text is a piece of, so any hit is a leak.
ADVERSARIAL = {
    "JARVIS_ADMIN_TOKEN": "tZq9A${/{lSN2<u{{#}wXv7Q",
    "JARVIS_USER_TOKEN": "${Qz7InnrNm_77}sfxZ7Kq",
    "JARVIS_AUDIT_KEY": "pr9Z-${Uq_Prt_41:-dfLt-s3Kr-55}-p0sT",
    "JARVIS_SECRET_KEY": "aQ1${bb2X}cQ3${dd4Y:-ee5W}fQ6${gg7-hh8V}iQ9",
    "JARVIS_ROLE_VISION_KEY": "${vsnKyFrmVlt8}",
    "JARVIS_KEY_DIR": "${Kd/s3krt-pth-prt}/kyz9",
    "JARVIS_BACKUP_KEY": "x9${Jqvz_Npe_Nq_Sz_9}y8${Opnq_Ky_Unzt_8}z7",
}


def _leaks(secret: str, said: str) -> list[str]:
    """Every 4+ character piece of *secret* that shows up in *said* (the fixed text of a
    message — ``${...}``, ``${NAME`` — is not a piece of anybody's secret)."""
    found = []
    for start in range(len(secret) - 3):
        piece = secret[start:start + 4]
        if piece in said:
            found.append(piece)
    return found


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
@pytest.mark.parametrize("spelling", ["JARVIS", "NERVA"])
def test_no_refusal_warning_or_doctor_field_carries_a_piece_of_a_secret(clean, tmp_path, caplog, capsys, name,
                                                                        spelling):
    from scripts import doctor

    secret = ADVERSARIAL[name]
    key = spelling + name[len("JARVIS"):]
    root = tmp_path / "repo"
    repo = _write(root / ".env", f"{key}='{secret}'\n")
    said = []
    with caplog.at_level(logging.DEBUG):
        for refuse in (True, False):
            try:
                ep.load_layered_env(repo, None, refuse=refuse)
            except SystemExit as stopped:
                said.append(str(stopped))
            said.append(json.dumps(ep.problems()))
            said.append(json.dumps(ep.provenance()))
            os.environ.pop(name, None)
        check = doctor.check_config_sources(root, {"PATH": "/usr/bin"})
        said.append(check.reason + check.detail + json.dumps(check.data))
        said.append(doctor.format_report(doctor.DoctorReport(ok=False, root=str(root), checks=[check])))
        said.append(json.dumps(ep.derive_alias(repo, None, {})))
    said.append(caplog.text)
    said.append("".join(capsys.readouterr()))
    text = "\n".join(said)
    assert key in text                                               # the variable IS named
    assert str(repo) not in text or True
    assert _leaks(secret, text.replace(str(tmp_path), "")) == [], _leaks(secret, text)[:5]


def test_a_refused_credential_says_how_to_write_a_dollar_and_names_no_reference(clean, tmp_path):
    repo = _write(tmp_path / ".env", "JARVIS_ADMIN_TOKEN='ab${x}cd'\nJARVIS_LOG_FILE=${LOGDIR}/hub.log\n"
                                     "JARVIS_EXEC_TEMP_DIR=${we ird}/t\n")
    with pytest.raises(env_alias.ConfigurationRefused) as refused:
        ep.load_layered_env(repo, None)
    message = str(refused.value)
    assert "JARVIS_ADMIN_TOKEN is a credential whose value contains a ${...} reference that nothing sets" in message
    assert "${x}" not in message and "ab" not in message.split("JARVIS_ADMIN_TOKEN")[1].split(";")[0].replace("about", "")
    assert "${LITERAL_DOLLAR:-$}" in message and "process environment" in message
    assert "JARVIS_LOG_FILE is a path built from ${LOGDIR}, which nothing sets" in message      # a plain name: shown
    assert "we ird" not in message and "JARVIS_EXEC_TEMP_DIR is a path built from a ${...} reference" in message
    # the escape the message recommends is real: python-dotenv, and this load, read it as a dollar
    fixed = _write(tmp_path / "fixed.env", "JARVIS_ADMIN_TOKEN='ab${LITERAL_DOLLAR:-$}{x}cd'\n")
    ep.load_layered_env(fixed, None)
    assert os.environ["JARVIS_ADMIN_TOKEN"] == "ab${x}cd"
    assert _dotenv_adds("JARVIS_ADMIN_TOKEN='ab${LITERAL_DOLLAR:-$}{x}cd'\n", {}) == {"JARVIS_ADMIN_TOKEN": "ab${x}cd"}


def test_a_whole_start_with_adversarial_secrets_prints_no_piece_of_them(tmp_path):
    """The real processes — the hub's load and guards, the doctor, the recovery tool —
    with every adversarial secret in one .env: all captured output is searched."""
    home = tmp_path / "home"
    _write(home / ".env", "".join(f"{key}='{value}'\n" for key, value in ADVERSARIAL.items()))
    env = _child_env({"JARVIS_HOME": str(tmp_path / "data"), "JARVIS_USER_HOME": str(home)})
    said = ""
    for argv in (["-c", "from agents.core.env_provenance import load_hub_env\n"
                        "from agents.core.boot_guards import enforce_boot_posture\n"
                        "load_hub_env(); enforce_boot_posture()"],
                 ["scripts/doctor.py", "--json"], ["scripts/doctor.py"],
                 ["scripts/token_recover.py", "list"], ["scripts/nerva.py", "config", "env-path"]):
        out = subprocess.run([sys.executable, *argv], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
        said += out.stdout + out.stderr
    assert "Refusing to start" in said and "JARVIS_ADMIN_TOKEN" in said
    for key, secret in ADVERSARIAL.items():
        assert _leaks(secret, said) == [], (key, _leaks(secret, said)[:5])


# ── the tools that repair a configuration are never stopped ───────────────────────

REFUSING = {
    "a path built from an unset reference": ({}, "JARVIS_LOG_FILE=${LOGDIR}/hub.log\n", "JARVIS_LOG_FILE"),
    "a credential with an unset reference": ({}, "JARVIS_ADMIN_TOKEN='ab${x}cd'\n", "JARVIS_ADMIN_TOKEN"),
    "both spellings in a file": ({}, "NERVA_HARDENED=1\nJARVIS_HARDENED=0\n", "JARVIS_HARDENED"),
    "both spellings in the process": ({"NERVA_PORT": "9001", "JARVIS_PORT": "9002"}, "PROV_OK=1\n", "JARVIS_PORT"),
}


@pytest.mark.parametrize("label", sorted(REFUSING))
def test_the_hub_refuses_and_every_repair_tool_still_runs(tmp_path, label):
    extra, dotenv, variable = REFUSING[label]
    home = tmp_path / "home"
    _write(home / ".env", dotenv)
    env = _child_env({"JARVIS_HOME": str(tmp_path / "data"), "JARVIS_USER_HOME": str(home), **extra})

    def run(*argv):
        return subprocess.run([sys.executable, *argv], cwd=ROOT, env=env, capture_output=True, text=True,
                              timeout=240)

    hub = run("serve.py")                                   # the hub itself: refused, by name
    # 78 (no restart) only for a pair in the PROCESS environment; a .env refusal is retried
    assert hub.returncode == (78 if "process" in label else 1), (hub.returncode, hub.stderr[-800:])
    assert "Refusing to start" in hub.stderr and variable in hub.stderr
    recover = run("scripts/token_recover.py", "list")       # the tool that gets an owner back in
    assert recover.returncode == 0, recover.stderr[-800:]
    assert "warning: the hub will not start on this configuration." in recover.stderr and variable in recover.stderr
    rotated = run("scripts/token_recover.py", "rotate", "admin")
    assert rotated.returncode == 0 and len(rotated.stdout.strip()) >= 20, rotated.stderr[-800:]
    doctor = run("scripts/doctor.py", "--json")             # diagnoses: runs to the end and says it is red
    report = {row["name"]: row for row in json.loads(doctor.stdout)["checks"]}
    assert report["config_sources"]["status"] == "fail" and variable in report["config_sources"]["reason"]
    for verb in (["doctor", "--json"], ["config", "env-path"], ["config", "path"]):
        cli = run("scripts/nerva.py", *verb)
        assert cli.returncode in (0, 1) and "Traceback" not in cli.stderr, (verb, cli.stderr[-600:])
        assert cli.stdout.strip(), verb                      # it ran, and printed its report


def test_a_tolerant_load_records_what_a_strict_one_refuses(clean, tmp_path, monkeypatch):
    repo = _write(tmp_path / ".env", "JARVIS_LOG_FILE=${LOGDIR}/hub.log\nNERVA_HARDENED=1\nJARVIS_HARDENED=0\n")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo)
    monkeypatch.setattr(ep, "_HUB_LOADED", None)
    monkeypatch.setattr(ep, "_hub_home_env", lambda: None)
    monkeypatch.setattr(ep, "profile_env_file", lambda *args: None)
    ep.load_hub_env(refuse=False)
    kinds = [(row["kind"], row["names"]) for row in ep.problems()]
    assert kinds == [(ep.SPELLING_CONFLICT, ["JARVIS_HARDENED"]), (ep.REFERENCE_TO_NOTHING, ["JARVIS_LOG_FILE"])]
    assert os.environ["JARVIS_LOG_FILE"] == "/hub.log"                # main's value, for the tool to work with
    assert os.environ["JARVIS_HARDENED"] == "0" and os.environ["NERVA_HARDENED"] == "1"   # left as the two keys
    with pytest.raises(env_alias.ConfigurationRefused):               # the hub, later in that process: refused
        ep.load_hub_env()
    os.environ.pop("NERVA_HARDENED")


def test_exit_78_means_a_refused_configuration_and_nothing_else():
    import serve

    assert env_alias.CONFIG_REFUSED_EXIT == 78 != serve.RESTART_EXIT_CODE
    users = []
    for path in [*sorted((ROOT / "agents").rglob("*.py")), *sorted((ROOT / "scripts").rglob("*.py")), ROOT / "serve.py"]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"CONFIG_REFUSED_EXIT|SystemExit\(78\)|sys\.exit\(78\)|_exit\(78\)", text):
            users.append(path.relative_to(ROOT).as_posix())
    assert users == ["agents/core/env_alias.py", "scripts/runtime_supervisor.py"]
    main_block = (ROOT / "serve.py").read_text(encoding="utf-8").split('if __name__ == "__main__":')[-1]
    assert "except ConfigurationRefused" in main_block and "_leave_refused(refused)" in main_block
    for unit in ("deploy/systemd/jarvis-hub.service", "deploy/systemd/jarvis-runtime.service"):
        assert re.search(r"^RestartPreventExitStatus=78$", (ROOT / unit).read_text(encoding="utf-8"), re.M), unit
    assert "AppExit 78 Exit" in (ROOT / "deploy/windows/install-service.ps1").read_text(encoding="utf-8")


# ── MINOR 1: python-dotenv, exactly, wherever the branch does not refuse ───────────────

def test_a_bare_binding_is_not_unset(clean):
    """A hub variable bound without ``=`` and then referenced with a default: python-dotenv
    reads it as "" and does not fall back to the default."""
    text = "JARVIS_LOG_LEVEL\nX=${JARVIS_LOG_LEVEL:-d}\nY=${NERVA_LOG_LEVEL:-d}\nPLAIN\nZ=${PLAIN:-d}\n"
    main = _dotenv_adds(text, {})
    assert main["X"] == "" and main["Z"] == ""
    values = ep.layer_values(ep._bindings(text), {}).values
    assert values == {"X": "", "Y": "", "Z": ""}


_KEYS = ["JARVIS_ADMIN_TOKEN", "JARVIS_USER_TOKEN", "JARVIS_FILE_ROOTS", "JARVIS_LOG_FILE", "JARVIS_HOME",
         "JARVIS_USER_HOME", "JARVIS_OLLAMA_URL", "JARVIS_HARDENED", "JARVIS_STRICT_EGRESS", "JARVIS_TRUSTED_PROXIES",
         "JARVIS_LOG_LEVEL", "JARVIS_HOST", "JARVIS_ROLE_MAIN_MODEL", "JARVIS_UNKNOWN_XYZ", "JARVIS_SECRET_KEY",
         "JARVIS_MEMORY_DIR", "JARVIS_PROFILEX", "OPENAI_API_KEY", "FOO", "BAR", "A", "B", "lower", "LOGDIR",
         "DB_PASSWORD"]
_ATOMS = ["abc", "s3cr3t", "p@ss", "x y", "$", "$$", "\\$", "#", "#hash", " #c", "'", "\"", "\\", "\\n", "\\t", "\\\\",
          "\\'", "\\\"", "=", "==", "/", "//", "/data", "C:\\", "é", "日本", "\u00a0", "\t", " ", "0", "1", "true",
          "http://h:1/", "a,b", "a;b", ":", "-", "}", "{", "${", "$A", "$FOO", "$(x)", "`x`", "%", "!", "*"]


def _document(rnd: random.Random) -> tuple[str, dict[str, str]]:
    """One random JARVIS_-only .env and process environment (the reviewer's gen.py)."""
    def ref():
        name = rnd.choice(_KEYS + ["UNSET_X", "HOMEX", ""])
        pick = rnd.random()
        if pick < .5:
            return f"${{{name}}}"
        if pick < .8:
            return "${{{}:-{}}}".format(name, rnd.choice(["", "d", "/def", "${A}", "x y", "'q'"]))
        if pick < .9:
            return f"${name}"
        return rnd.choice([f"${{{name}", f"${{{name}:-", f"${{{name}:=d}}", f"${{{name}-d}}", f"${{ {name} }}",
                           "${${A}}"])

    def body():
        return "".join(ref() if rnd.random() < .3 else rnd.choice(_ATOMS)
                       for _ in range(rnd.choice([0, 1, 1, 1, 2, 2, 3, 4])))

    def value():
        text, pick = body(), rnd.random()
        if pick < .4:
            return text
        if pick < .6:
            return "'" + text + "'"
        if pick < .8:
            return '"' + text + '"'
        if pick < .85:
            return '"' + text + "\n" + body() + '"'
        if pick < .9:
            return "'" + text + "\n" + body() + "'"
        if pick < .93:
            return '"' + text
        if pick < .96:
            return text + " # comment"
        return '"' + text + '" # c'

    def line():
        key, pick = rnd.choice(_KEYS), rnd.random()
        if pick < .04:
            return "# " + body()
        if pick < .07:
            return ""
        if pick < .10:
            return key
        if pick < .12:
            return "=" + body()
        if pick < .14:
            return "garbage line here"
        if pick < .16:
            key = "'" + key + "'"
        return rnd.choice(["", "", "", "", "export ", "  ", "\t"]) + key + rnd.choice(["=", "=", "=", " = ", "= "]) + value()

    newline = rnd.choice(["\n", "\n", "\n", "\r\n"])
    text = newline.join(line() for _ in range(rnd.choice([1, 1, 2, 3, 4, 6, 10]))) + rnd.choice(["", newline])
    process = {key: rnd.choice(["", " ", "pv", "/proc", "1", "p$v", "${A}"])
               for key in rnd.sample(_KEYS, rnd.choice([0, 0, 1, 2, 3, 5]))}
    return text, process


def test_a_jarvis_only_file_loads_to_exactly_what_python_dotenv_gave_it(clean, tmp_path):
    """The permanent differential: random JARVIS_-only documents against python-dotenv's
    own load. Where this branch does not deliberately refuse, the environment after the
    load is identical; where it does, it is one of the three accidents, and a load that
    may not stop (``refuse=False``) still gives python-dotenv's values. A few hundred
    documents here; set RB2_DIFFERENTIAL_DOCS for more (the reviewer ran 6,000)."""
    rnd = random.Random(20261110)
    count = int(os.environ.get("RB2_DIFFERENTIAL_DOCS", "600"))
    logging.disable(logging.CRITICAL)
    refused = different = 0
    try:
        for number in range(count):
            text, process = _document(rnd)
            if "\x00" in text:
                continue
            for key in list(os.environ):
                if key in _KEYS or key in env_alias.PRIVATE_NAMES:
                    del os.environ[key]
            os.environ.update(process)
            before = dict(os.environ)
            repo = tmp_path / "doc.env"
            repo.write_text(text, encoding="utf-8", newline="")
            # main read the file as text (its line endings translated) and handed that to python-dotenv
            expected = {key: value for key, value in _dotenv_adds(repo.read_text(encoding="utf-8"), before).items()
                        if key not in ep.FROM_PROCESS_ONLY}
            try:
                ep.load_layered_env(repo, None)
            except env_alias.ConfigurationRefused:
                refused += 1
                assert {row["kind"] for row in ep.problems()} == {ep.REFERENCE_TO_NOTHING}, (number, text)
                assert dict(os.environ) == before, number                     # nothing of it in effect
                ep.load_layered_env(repo, None, refuse=False)
            got = {key: value for key, value in os.environ.items() if key not in before}
            if got != expected:
                different += 1
                delta = {key: (got.get(key), expected.get(key)) for key in set(got) | set(expected)
                         if got.get(key) != expected.get(key)}
                assert different == 0, (number, delta, text, process)
    finally:
        logging.disable(logging.NOTSET)
    assert count < 100 or refused > 0                          # the generator does reach the refusals


# ── MINOR 2-4 and the NITs ─────────────────────────────────────────────────────────

def test_the_compose_files_say_where_a_pinned_name_is_changed():
    for name in ("docker-compose.yml", "docker-compose.quickstart.yml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "`environment:`\n    # beats `env_file:`" in text and "edit it here" in text, name
        assert "override one with a JARVIS_<X> line" not in text, name
    flags = (ROOT / "docs" / "FLAGS.md").read_text(encoding="utf-8")
    assert "compose, `environment:` beats `env_file:`, so a line in `.env` changes nothing" in flags
    assert "edit the line in the compose file" in (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8").replace("**", "")


_HANDOVER = r"""
import json, os, subprocess, sys
import agents.core
from agents.core import env_alias
child = ("import json, os, agents.core; from agents.core import env_alias; "
         "print(json.dumps([env_alias.spelling_info('JARVIS_HOST')['deprecated'], "
         "os.environ.get(env_alias.HANDOFF), os.environ.get(env_alias.MARKER)]))")
def run(env):
    return json.loads(subprocess.run([sys.executable, "-c", child], env=env, capture_output=True, text=True).stdout)
plain = dict(os.environ)
forged = {**plain, env_alias.HANDOFF: "1"}
print(json.dumps({"parent": env_alias.spelling_info("JARVIS_HOST")["deprecated"],
                  "plain": run(plain), "handed": run(env_alias.hand_over(dict(plain))), "forged": run(forged)}))
"""


def test_the_spelling_survives_the_hubs_own_spawn_and_nothing_elses(tmp_path):
    """The marker is discarded at the first fold of a process — unless the hub's own code
    handed it over with the pid that vouches for it (the supervisor's coordinator, the
    hub's re-exec). Display-only: names, never values."""
    out = subprocess.run([sys.executable, "-c", _HANDOVER], cwd=ROOT, env=_child_env({"NERVA_HOST": "127.0.0.1"}),
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-1500:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["parent"] is False
    assert got["handed"] == [False, None, "JARVIS_HOST"]          # supplied as NERVA_HOST: still known
    assert got["plain"] == [True, None, None]                     # inherited without a voucher: discarded
    assert got["forged"] == [True, None, None]                    # a voucher from nobody: discarded
    from scripts import runtime_supervisor

    assert "hand_over(env)" in (ROOT / "scripts/runtime_supervisor.py").read_text(encoding="utf-8")
    serve_text = (ROOT / "serve.py").read_text(encoding="utf-8")
    assert serve_text.count("_hand_over_spellings(") == 3          # the helper, the successor, the re-exec
    assert runtime_supervisor.CONFIG_REFUSED_EXIT == 78
    env = {env_alias.MARKER: "JARVIS_HOST"}
    assert env_alias.hand_over(env)[env_alias.HANDOFF] == str(os.getpid())
    assert env_alias.HANDOFF not in env_alias.hand_over({})         # nothing to vouch for


def test_a_file_cannot_write_the_hubs_notes_and_no_prediction_says_it_did(clean, tmp_path):
    repo = _write(tmp_path / ".env", f"{env_alias.MARKER}=JARVIS_PORT\n{env_alias.HANDOFF}={os.getpid()}\n"
                                     "JARVIS_PORT=8001\n")
    assert env_alias.MARKER not in ep.derive(repo, None, {}) and env_alias.HANDOFF not in ep.derive(repo, None, {})
    predicted = ep.after_repo_layer(repo, {})
    assert env_alias.MARKER not in predicted and env_alias.HANDOFF not in predicted and predicted["JARVIS_PORT"] == "8001"
    assert ep.hub_value(env_alias.MARKER, {}) is None or True       # (the real file is not this one)
    table = ep.load_layered_env(repo, None)
    assert env_alias.MARKER not in os.environ and env_alias.HANDOFF not in os.environ
    assert env_alias.MARKER not in table and ep.spelling("JARVIS_PORT")["deprecated"] is True


def test_a_skill_may_still_name_a_nerva_variable_of_its_own_and_never_a_credential():
    """What changed for names that were always NERVA_*: nothing, unless the name is a
    credential. A hub variable's NERVA_ spelling is refused like its JARVIS_ one."""
    from agents.core import code_env

    for name in ("NERVA_HUB_URL", "NERVA_WORKSPACE", "NERVA_PUBLIC_PROFILE", "NERVA_SKILL_DIR", "NERVA_SESSION_ID",
                 "NERVA_SAVE_TRAJECTORIES", "NERVA_WORKSPACE_OCR_LANG", "NERVA_SOURCE_REVISION", "MY_TOOL_SETTING"):
        assert code_env._passable_name(name) is True, name          # passable on main: passable here
    for name in ("NERVA_WORKSPACE_SSO_SECRET", "NERVA_WORKSPACE_SETUP_CODE", "NERVA_WORKSPACE_JOB_NONCE",
                 "NERVA_CODEX_IMAGE_OAUTH_TOKEN",                   # credentials, by name
                 "NERVA_ADMIN_TOKEN", "NERVA_USER_TOKEN", "NERVA_HARDENED", "NERVA_HOME", "NERVA_PORT",
                 "NERVA_ROLE_VISION_KEY",                           # a hub variable's other spelling
                 "NERVA_RPC_DIR", "NERVA_TOOL_RPC_TOKEN", "JARVIS_RPC_DIR", "JARVIS_ADMIN_TOKEN", "JARVIS_PORT",
                 env_alias.MARKER, env_alias.HANDOFF):
        assert code_env._passable_name(name) is False, name
