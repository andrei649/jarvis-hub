"""RB-2, third review — small corrections, each pinned on the real mechanism.

M1  a tolerant load (``refuse=False``, the recovery tool's) kept a refused pair under both
    keys and took only the ``JARVIS_`` process-only name back out, so a ``.env`` moved the
    data root or the profile through its ``NERVA_`` line.
m2  the credential refusal used a substring test on the name and caught a token budget, a
    flag and a secret handle: it is an explicit, reviewed set now.
m3  only read-only diagnostics run under a conflicting pair; a verb that writes or sends
    refuses.
m4  exit 78 (no restart) is for a pair in the PROCESS environment only; a refusal from a
    ``.env`` file is an ordinary failure the service manager retries.
m5  a reference that is defined and blank is the operator's value (``test_rb2_review2``'s
    table holds the rows).

What boots on main and refuses here, in full: a path-typed variable a ``.env`` builds from
a reference nothing sets; a credential (the explicit set) a ``.env`` builds from a
reference nothing sets; one variable under both spellings with different values in one
layer.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
import agents.web  # noqa: E402,F401  (before any test has a token in the environment)
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
    saved = dict(os.environ)
    for key in list(os.environ):
        if key in env_alias.PRIVATE_NAMES or env_config.other_spelling(key):
            monkeypatch.delenv(key)
    monkeypatch.setattr(ep, "_PROBLEMS", [])
    monkeypatch.setattr(ep, "_ROOTS_WARNED", set())
    yield monkeypatch
    for key in set(os.environ) - set(saved):
        os.environ.pop(key, None)


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in _KEPT}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", **extra})
    return env


def _run(argv, env, **kwargs):
    return subprocess.run([sys.executable, *argv], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=240, **kwargs)


# ── MAJOR 1: a tolerant load cannot move the data root or the profile ────────────────

@pytest.mark.parametrize("name", sorted(ep.FROM_PROCESS_ONLY))
def test_a_tolerant_load_leaves_a_process_only_name_out_under_both_spellings(clean, tmp_path, name):
    new = "NERVA_" + name[len("JARVIS_"):]
    for text in (f"{new}=/srv/NEWROOT\n{name}=/srv/OLDROOT\n", f"{name}=/srv/OLDROOT\n{new}=/srv/NEWROOT\n",
                 f"{new}=/srv/NEWROOT\n", f"{name}=/srv/OLDROOT\n"):
        repo = _write(tmp_path / ".env", text + "PROV_M1=1\n")
        table = ep.load_layered_env(repo, None, refuse=False)
        assert name not in os.environ and new not in os.environ, text
        assert env_config.env_str(name, "<unset>") == "<unset>"
        assert table[name] == {"layer": "repo_env", "shadowed": []} and new not in table
        assert ep.provenance()[name]["layer"] == "repo_env"
        assert ep.after_repo_layer(repo, {}).get(name) is None and ep.after_repo_layer(repo, {}).get(new) is None
        os.environ.pop("PROV_M1", None)
    assert [row["kind"] for row in ep.problems()] == []            # the last file: one spelling, no pair


def test_the_recovery_tool_writes_where_a_jarvis_only_file_would(tmp_path):
    """Both spellings of PROFILE and of HOME in the data-home .env, differently: the token
    store and the data root are exactly where they are for the JARVIS_-only file — where
    the process environment puts them (a .env cannot set either name)."""
    data = tmp_path / "data"
    home = tmp_path / "home"
    probe = ("import json, sys\nsys.path.insert(0, 'scripts')\nimport token_recover\n"
             "from agents.core.env_provenance import load_hub_env\nload_hub_env(refuse=False)\n"
             "from agents.core import paths\nfrom agents.core.security import token_store\n"
             "print('PROBE' + json.dumps({'root': str(paths.data_root()), 'profile': paths.profile_name(),"
             " 'store': str(getattr(token_store.get_token_store(), '_path', '?'))}))\n")
    seen = {}
    for label, text in (("jarvis only", "JARVIS_HOME=/srv/OLDROOT\nJARVIS_PROFILE=old\n"),
                        ("both", "NERVA_HOME=/srv/NEWROOT\nJARVIS_HOME=/srv/OLDROOT\n"
                                 "NERVA_PROFILE=work\nJARVIS_PROFILE=old\n")):
        _write(home / ".env", text)
        env = _child_env({"JARVIS_HOME": str(data), "JARVIS_USER_HOME": str(home)})
        out = _run(["-c", probe], env)
        assert out.returncode == 0, out.stderr[-1500:]
        seen[label] = json.loads(out.stdout.rsplit("PROBE", 1)[1])
        rotated = _run(["scripts/token_recover.py", "rotate", "admin"], env)
        assert rotated.returncode == 0 and f"token store: {data}" in rotated.stderr, rotated.stderr[-800:]
    assert seen["both"] == seen["jarvis only"]
    assert seen["both"]["root"] == str(data) and seen["both"]["profile"] is None
    assert seen["both"]["store"].startswith(str(data)) and "NEWROOT" not in json.dumps(seen)


# ── MINOR 2: the credential refusal is an explicit set ───────────────────────────────

def test_every_masked_hub_variable_is_classified_as_a_credential_or_not():
    """``masked`` (a substring test, for hiding a value on a screen) is unchanged. What the
    load REFUSES is the reviewed set — and a new hub name ``masked`` matches must be put
    in one list or the other before it ships."""
    matched = {suffix for suffix in env_config.HUB_ENV_SUFFIXES if ep.masked("JARVIS_" + suffix)}
    unclassified = sorted(matched - env_alias.CREDENTIALS - env_alias.NOT_CREDENTIALS)
    assert not unclassified, (
        f"{unclassified}: masked by name and neither in env_alias.CREDENTIALS nor in NOT_CREDENTIALS — "
        "decide whether a .env that builds it from an unset ${...} must refuse to start.")
    assert matched == env_alias.CREDENTIALS | env_alias.NOT_CREDENTIALS            # nothing stale
    assert not env_alias.CREDENTIALS & env_alias.NOT_CREDENTIALS
    assert {"BUDGET_MAX_TOKENS", "PASSIVE_CAPTURE", "HA_TOKEN_REF", "KEY_DIR",
                                         "NOUS_CLIENT_ID"} == env_alias.NOT_CREDENTIALS
    for name in ("JARVIS_ADMIN_TOKEN", "NERVA_USER_TOKEN", "JARVIS_AUDIT_KEY", "NERVA_ROLE_VISION_KEY",
                 "JARVIS_ROLE_VIDEO_FALLBACK_2_KEY", "NERVA_VLM_KEY"):
        assert env_alias.credential(name), name
    for name in ("JARVIS_BUDGET_MAX_TOKENS", "NERVA_PASSIVE_CAPTURE", "JARVIS_HA_TOKEN_REF", "JARVIS_KEY_DIR",
                 "JARVIS_ROLE_VISION_MODEL", "JARVIS_PORT", "OPENAI_API_KEY", "NERVA_WORKSPACE_SSO_SECRET"):
        assert not env_alias.credential(name), name
    assert ep.masked("JARVIS_BUDGET_MAX_TOKENS") and ep.masked("NERVA_PASSIVE_CAPTURE")    # display: unchanged


@pytest.mark.parametrize("line", ["JARVIS_BUDGET_MAX_TOKENS=${BUDGET}", "JARVIS_PASSIVE_CAPTURE=${CAPTURE}",
                                  "JARVIS_HA_TOKEN_REF={{secret:${HA_NAME}}}"])
def test_a_masked_name_that_is_not_a_credential_starts_as_on_main(tmp_path, line):
    home = tmp_path / "home"
    _write(home / ".env", line + "\n")
    out = _run(["-c", "from agents.core.env_provenance import load_hub_env\n"
                      "from agents.core.boot_guards import enforce_boot_posture\n"
                      "import os\nload_hub_env(); enforce_boot_posture()\n"
                      f"print('VALUE=' + repr(os.environ[{line.split('=')[0]!r}]))"],
               _child_env({"JARVIS_HOME": str(tmp_path / "data"), "JARVIS_USER_HOME": str(home)}))
    assert out.returncode == 0 and "Refusing" not in out.stderr, out.stderr[-800:]
    assert "VALUE=" in out.stdout and "nothing sets" in out.stderr       # main's value, and one warning


# ── MINOR 3: only read-only diagnostics run under a conflicting pair ─────────────────

def test_a_verb_that_writes_or_sends_refuses_and_a_read_only_one_runs(clean, monkeypatch):
    from agents.cli import env_spelling, nerva

    ran = []
    monkeypatch.setattr(nerva, "main", lambda raw: ran.append(raw) or 0)
    clean.setenv("NERVA_ADMIN_TOKEN", "one-admin-token-a1a1")
    clean.setenv("JARVIS_ADMIN_TOKEN", "another-admin-token-b2b2")
    read_only = (["doctor"], ["doctor", "--json"], ["completion", "bash"], ["logs"], ["config", "path"],
                 ["config", "env-path"], ["config", "--json", "path"], ["-p", "work", "config", "env-path"])
    for argv in read_only:
        assert env_spelling.main(list(argv)) == 0 and ran[-1] == list(argv), argv
    refused = (["config", "set", "system.name", "x"], ["config", "unset", "system.name"], ["config", "edit"],
               ["config", "migrate"], ["config", "list"], ["config", "get", "system.name"], ["config"],
               ["support", "bundle"], ["uninstall"], ["status"], ["chat"], ["send", "hello"], ["backup", "create"],
               ["secrets", "set", "x"], ["jobs", "list"], [])
    for argv in refused:
        before = len(ran)
        assert env_spelling.main(list(argv)) == nerva.EXIT_USAGE and len(ran) == before, argv
    assert not hasattr(env_spelling, "REPAIR_VERBS")
    logs_source = (ROOT / "agents/cli/nerva.py").read_text(encoding="utf-8").split("def cmd_logs(")[1].split("\ndef ")[0]
    assert "ctx.client(" not in logs_source and "log_path(ctx.environ)" in logs_source   # local file, nothing sent


def test_config_set_refuses_in_a_real_process_and_names_the_variable(tmp_path):
    env = _child_env({"NERVA_HOME": str(tmp_path / "new"), "JARVIS_HOME": str(tmp_path / "old")})
    out = _run(["scripts/nerva.py", "config", "set", "system.name", "x"], env)
    assert out.returncode == 2 and "NERVA_HOME / JARVIS_HOME" in out.stderr
    assert not (tmp_path / "old").exists() and not (tmp_path / "new").exists()        # nothing written
    out = _run(["scripts/nerva.py", "config", "path"], env)
    assert out.returncode == 0 and "warning: the hub will not start" in out.stderr


# ── MINOR 4: which refusal is which exit status ───────────────────────────────────

STATUS = {
    "both spellings in the process environment": ({"NERVA_PORT": "9001", "JARVIS_PORT": "9002"}, "PROV_OK=1\n", 78),
    "both spellings in a .env": ({}, "NERVA_HARDENED=1\nJARVIS_HARDENED=0\n", 1),
    "a path built from an unset reference": ({}, "JARVIS_LOG_FILE=${LOGDIR}/hub.log\n", 1),
    "a credential built from an unset reference": ({}, "JARVIS_ADMIN_TOKEN='ab${x}cd'\n", 1),
}


@pytest.mark.parametrize("label", sorted(STATUS))
def test_only_a_process_pair_is_the_no_restart_status(tmp_path, label):
    extra, dotenv, status = STATUS[label]
    home = tmp_path / "home"
    _write(home / ".env", dotenv)
    env = _child_env({"JARVIS_HOME": str(tmp_path / "data"), "JARVIS_USER_HOME": str(home), **extra})
    hub = _run(["serve.py"], env)
    assert hub.returncode == status and hub.stderr.count("Refusing to start") == 1, (hub.returncode, hub.stderr[-600:])
    # the staged-restore load at the top of serve.py takes the same way out
    staged = _run(["-c", "import agents.core.backup as backup\nbackup.boot_restore_due = lambda: True\nimport serve"],
                  env)
    assert staged.returncode == status and "Refusing to start" in staged.stderr, (staged.returncode, staged.stderr[-600:])
    coordinator = _run(["scripts/coordinator.py"], {**env, "JARVIS_RUNTIME_FAKE_LLM": "1"})
    assert coordinator.returncode == status, (coordinator.returncode, coordinator.stderr[-600:])


def test_a_refusal_carries_its_status_and_a_file_mid_save_is_not_permanent(clean, tmp_path):
    """The reviewer's io.py: a reference to a variable defined in a file that was caught
    empty, absent or cut by a save refuses as before — and is retried, not final."""
    home = _write(tmp_path / "h.env", "JARVIS_LOG_FILE=${LOGDIR}/hub.log\n")
    for repo in (_write(tmp_path / "empty.env", ""), tmp_path / "absent.env",
                 _write(tmp_path / "cut.env", "LOGDIR_MAIN=/var/log\n")):
        with pytest.raises(env_alias.ConfigurationRefused) as refused:
            ep.load_layered_env(repo, home)
        assert refused.value.exit_status == 1 and "JARVIS_LOG_FILE" in str(refused.value)
    ep.load_layered_env(_write(tmp_path / "whole.env", "LOGDIR=/var/log\n"), home)      # the save finished
    assert os.environ["JARVIS_LOG_FILE"] == "/var/log/hub.log"
    with pytest.raises(env_alias.ConfigurationRefused) as refused:
        env_alias.refuse_conflicts({"NERVA_HOST": "a", "JARVIS_HOST": "b"})
    assert refused.value.exit_status == env_alias.CONFIG_REFUSED_EXIT == 78
    with pytest.raises(env_alias.ConfigurationRefused) as refused:
        ep.load_layered_env(_write(tmp_path / "pair.env", "NERVA_HOST=a\nJARVIS_HOST=b\n"), None)
    assert refused.value.exit_status == 1
    assert env_alias.ConfigurationRefused("x").exit_status == 1


# ── NITs ──────────────────────────────────────────────────────────────────────────

def test_the_root_line_is_said_once_per_boot(clean, tmp_path, caplog, capsys):
    clean.setenv("JARVIS_FILE_ROOTS", "/")
    with caplog.at_level(logging.WARNING):
        ep.load_layered_env(_write(tmp_path / ".env", "PROV_X=1\n"), None)     # serve.py's load
        boot_guards.assert_parseable_posture_flags()                             # serve.py's guard
        boot_guards.assert_parseable_posture_flags()                             # the lifespan's guard
    said = [record.getMessage() for record in caplog.records if "filesystem root" in record.getMessage()]
    assert len(said) == 1 and said[0].startswith("[SECURITY] JARVIS_FILE_ROOTS is set to the filesystem root")
    assert "filesystem root" not in "".join(capsys.readouterr())


def test_no_process_is_handed_one_value_of_a_refused_pair(tmp_path, clean):
    """``hub_value`` (the supervisor's look into the .env files) answers None for a pair
    the load refuses, so the coordinator is not started with one of its two values."""
    home = _write(tmp_path / "home" / ".env", "NERVA_RUNTIME_LOG=/var/a.jsonl\nJARVIS_RUNTIME_LOG=/var/b.jsonl\n"
                                              "NERVA_PORT=8101\n")
    shell = {"JARVIS_USER_HOME": str(tmp_path / "home")}
    assert ep.hub_value("JARVIS_RUNTIME_LOG", shell) is None and ep.hub_value("NERVA_RUNTIME_LOG", shell) is None
    assert ep.hub_value("JARVIS_PORT", shell) == "8101"
    _write(home, "NERVA_RUNTIME_LOG=/var/a.jsonl\n")
    assert ep.hub_value("JARVIS_RUNTIME_LOG", shell) == "/var/a.jsonl"


def test_the_workspace_session_cookies_are_not_passable_to_a_child():
    from agents.core import code_env

    for name in ("NERVA_WS_SESSION", "NERVA_WS_ADMIN_SESSION", "NERVA_WORKSPACE_SETUP_CODE"):
        assert code_env._passable_name(name) is False, name
    assert code_env._passable_name("NERVA_HUB_URL") is True


def test_the_repo_file_prediction_holds_no_value_of_a_refused_pair(tmp_path):
    """Fourth review: `after_repo_layer` (and so `hub_value`) handed out one of the two
    values of a pair the load refuses when the pair was in the REPO .env."""
    from agents.core import env_provenance

    repo = tmp_path / ".env"
    repo.write_text("JARVIS_RUNTIME_LOG=/var/log/a.jsonl\nNERVA_RUNTIME_LOG=/var/log/b.jsonl\n"
                    "JARVIS_PORT=8123\n", encoding="utf-8")
    merged = env_provenance.after_repo_layer(repo, {})
    assert "JARVIS_RUNTIME_LOG" not in merged and "NERVA_RUNTIME_LOG" not in merged
    assert merged.get("JARVIS_PORT") == "8123"                 # the rest of the file still counts


@pytest.mark.parametrize("doc", ["docs/PACKAGING.md", "docs/PHONE_ACCESS.md"])
def test_the_packaged_recovery_removes_the_tokens_under_both_spellings(doc):
    """A new install's `.env` spells the tokens `NERVA_…`. A recovery that removes only the
    `JARVIS_…` lines leaves a token in place, and once `tokens.db` is gone a rotated-away
    or revoked one works again (H273's review rounds h and i, now for both spellings)."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / doc).read_text(encoding="utf-8")
    recovery = text[text.index("ships"):]
    for name in ("NERVA_ADMIN_TOKEN", "NERVA_USER_TOKEN", "NERVA_HOST"):
        assert name in recovery, name
    assert recovery.index("NERVA_USER_TOKEN") < recovery.index("tokens.db", recovery.index("NERVA_USER_TOKEN"))
