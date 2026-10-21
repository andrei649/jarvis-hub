"""H004: Bash and Zsh offer only children of the current argparse node.

H574: they also carry each command's help text and complete profile names after the
root ``-p``/``--profile`` option, listing the profiles directory at completion time.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agents.cli.completion import completion_nodes, help_line
from agents.cli.nerva import Context, _verb_index, build_parser, completion_script, main


def _script(tmp_path, shell, parser, profiles_base=None):
    path = tmp_path / f"nerva.{shell}"
    path.write_text(completion_script(shell, parser, profiles_base=profiles_base), encoding="utf-8")
    return path


def _env(**extra):
    """The test process's environment without the data-root variables, plus *extra*."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_PROFILE")}
    env.update(extra)
    return env


def _complete(shell, script, *words, env=None, listing=False):
    """Candidates the script offers for *words* (the last one is being completed).

    *listing* asks for what the shell would display rather than insert: bash's second
    <Tab> (``COMP_TYPE`` 63), zsh's ``compadd -d`` display strings.
    """
    if shell == "bash":
        body = r'''source "$1"
shift
COMP_WORDS=(nerva "$@")
COMP_CWORD=$((${#COMP_WORDS[@]} - 1))
COMP_TYPE=${NERVA_COMP_TYPE:-9}
_nerva
printf '%s\n' "${COMPREPLY[@]}"'''
        argv = ["bash", "--noprofile", "--norc", "-c", body, "bash", str(script), *words]
    else:
        body = r'''compadd() {
  local disp="" i=0 candidate
  local -a shown
  while (( $# )) && [[ "$1" != "--" ]]; do
    case "$1" in
      -l) shift ;;
      -d) disp="$2"; shift 2 ;;
      *) return 2 ;;
    esac
  done
  [[ "$1" == "--" ]] || return 2
  shift
  [[ -n "$disp" ]] && shown=("${(@P)disp}")
  for candidate in "$@"; do
    (( i++ ))
    [[ "$candidate" == "${words[CURRENT]}"* ]] || continue
    if [[ -n "$NERVA_COMP_TYPE" ]]; then print -r -- "${shown[i]}"; else print -r -- "$candidate"; fi
  done
}
source "$1"
shift
words=(nerva "$@")
CURRENT=${#words}
_nerva'''
        argv = ["zsh", "-f", "-c", body, "zsh", str(script), *words]
    env = dict(env if env is not None else _env())
    if listing:
        env["NERVA_COMP_TYPE"] = "63"
    done = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False, env=env)
    assert done.returncode == 0, done.stderr
    return [line for line in done.stdout.splitlines() if line]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_live_parser_completes_root_and_one_path_only(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    script = _script(tmp_path, shell, build_parser())
    assert subprocess.run([shell, "-n", str(script)], capture_output=True, text=True).returncode == 0
    root = _complete(shell, script, "")
    assert "jobs" in root and "completion" in root
    assert _complete(shell, script, "jobs", "doc") == ["doctor"]
    assert _complete(shell, script, "jobs", "doctor", "") == []
    assert _complete(shell, script, "jobs", "bogus", "") == []
    assert _complete(shell, script, "bogus", "") == []


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_nested_parser_and_aliases_follow_exact_path(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    parser = argparse.ArgumentParser()
    root = parser.add_subparsers()
    primary = root.add_parser("primary", aliases=["other"])
    nested = primary.add_subparsers().add_parser("nested")
    nested.add_subparsers().add_parser("leaf")
    script = _script(tmp_path, shell, parser)

    assert _complete(shell, script, "pri") == ["primary"]
    assert _complete(shell, script, "other", "") == ["nested"]
    assert _complete(shell, script, "primary", "nested", "le") == ["leaf"]
    assert _complete(shell, script, "other", "nested", "leaf", "") == []
    assert _complete(shell, script, "other", "wrong", "") == []


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_sensitive_parser_names_are_literal_data(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    marker = tmp_path / "executed"
    hostile = f"literal'$(touch {marker})"
    parser = argparse.ArgumentParser()
    root = parser.add_subparsers()
    child = root.add_parser(hostile)
    child.add_subparsers().add_parser("nested;$(false)")
    for name in ("colon:thing", "[bracket]", "-dash"):
        root.add_parser(name)
    script = _script(tmp_path, shell, parser)

    assert subprocess.run([shell, "-n", str(script)], capture_output=True, text=True).returncode == 0
    assert _complete(shell, script, "lit") == [hostile]
    assert _complete(shell, script, hostile, "nested") == ["nested;$(false)"]
    assert _complete(shell, script, "colon") == ["colon:thing"]
    assert _complete(shell, script, "[bra") == ["[bracket]"]
    assert _complete(shell, script, "-da") == ["-dash"]
    assert not marker.exists()


# ── H574: help text ──────────────────────────────────────────────────────────

def _help_of(parser, path, name):
    return dict(completion_nodes(parser)[path])[name]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_listing_carries_each_commands_help_text(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    parser = build_parser()
    script = _script(tmp_path, shell, parser)
    doctor_help = _help_of(parser, ("jobs",), "doctor")
    assert doctor_help                                    # the live parser documents it
    listed = _complete(shell, script, "jobs", "", listing=True)
    line = next(row for row in listed if row.startswith("doctor "))
    assert line.endswith(f"  -- {doctor_help}")
    # what is inserted stays the bare name
    assert "doctor" in _complete(shell, script, "jobs", "")
    # a single match is inserted bare even in bash's listing mode
    assert _complete("bash", _script(tmp_path, "bash", parser), "jobs", "doc", listing=True) == ["doctor"]
    root = _complete(shell, script, "", listing=True)
    assert any(row.startswith("jobs ") and "  -- " in row for row in root)


def test_every_live_command_has_help_text_to_complete():
    missing = [" ".join((*path, name)) for path, kids in completion_nodes(build_parser()).items()
               for name, text in kids if not text]
    assert missing == []


def test_help_line_is_one_bounded_printable_line():
    assert help_line("two\nlines\tand\x1b[31m  colour") == "two lines and [31m colour"
    assert help_line(argparse.SUPPRESS) == "" and help_line(None) == ""
    assert len(help_line("x" * 500)) == 72 and help_line("x" * 500).endswith("…")


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_hostile_help_text_is_literal_data(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    marker = tmp_path / "executed"
    hostile = f"it's $(touch {marker}) `touch {marker}` \"%s"
    parser = argparse.ArgumentParser()
    root = parser.add_subparsers()
    root.add_parser("alpha", help=hostile)
    root.add_parser("alpine", help="plain")
    script = _script(tmp_path, shell, parser)
    assert subprocess.run([shell, "-n", str(script)], capture_output=True, text=True).returncode == 0
    listed = _complete(shell, script, "al", listing=True)
    assert any(row.endswith(f"  -- {help_line(hostile)}") for row in listed), listed
    assert not marker.exists()


# ── H574: profile names ──────────────────────────────────────────────────────

def _profiles(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "home-profiles"
    for name in ("work", "lab-2", "Bad!", "default"):
        (root / name).mkdir(parents=True)
    (root / "a-file").write_text("not a profile")
    (root / "link").symlink_to(root / "work")
    return home


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_profile_option_completes_profiles_on_disk(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    home = _profiles(tmp_path)
    script = _script(tmp_path, shell, build_parser(), profiles_base=str(tmp_path / "unused"))
    env = _env(JARVIS_HOME=str(home))
    assert sorted(_complete(shell, script, "-p", "", env=env)) == ["default", "lab-2", "work"]
    assert _complete(shell, script, "--profile", "wo", env=env) == ["work"]
    # a profile created after the script was generated appears too
    (tmp_path / "home-profiles" / "later").mkdir()
    assert "later" in _complete(shell, script, "-p", "", env=env)
    # after the profile, completion continues at the verb, then along the path
    assert "jobs" in _complete(shell, script, "-p", "work", "", env=env)
    assert _complete(shell, script, "--profile", "work", "jobs", "doc", env=env) == ["doctor"]
    assert _complete(shell, script, "-p", "work", "jobs", "doctor", "", env=env) == []
    # the option itself completes, with its help
    assert _complete(shell, script, "--pro", env=env) == ["--profile"]
    listed = _complete(shell, script, "-", env=env, listing=True)
    assert any(row.startswith("--profile ") and "JARVIS_PROFILE" in row for row in listed)


def test_bash_completes_the_equals_form(tmp_path):
    home = _profiles(tmp_path)
    script = _script(tmp_path, "bash", build_parser())
    env = _env(JARVIS_HOME=str(home))
    # bash splits --profile=wo at '=' (COMP_WORDBREAKS)
    assert _complete("bash", script, "--profile", "=", "wo", env=env) == ["work"]
    assert _complete("bash", script, "--profile", "=", "work", "jobs", "doc", env=env) == ["doctor"]


def test_zsh_skips_the_equals_form_before_the_verb(tmp_path):
    if not shutil.which("zsh"):
        pytest.skip("zsh is not installed")
    script = _script(tmp_path, "zsh", build_parser())
    assert _complete("zsh", script, "--profile=work", "jobs", "doc") == ["doctor"]
    assert "jobs" in _complete("zsh", script, "--profile=work", "")


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_attached_short_profile_form_is_skipped_before_the_verb(tmp_path, shell):
    # H574 review round 4: nerva.py accepts `-pwork`; completion treated it as the verb.
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    script = _script(tmp_path, shell, build_parser())
    assert _complete(shell, script, "-pwork", "jobs", "doc") == ["doctor"]
    assert "jobs" in _complete(shell, script, "-pwork", "")
    assert _complete(shell, script, "-pwork", "-p", "lab", "jobs", "doc") == ["doctor"]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_profile_root_falls_back_to_the_generated_install_root(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    home = _profiles(tmp_path)
    script = _script(tmp_path, shell, build_parser(), profiles_base=str(home) + "/")
    assert sorted(_complete(shell, script, "-p", "")) == ["default", "lab-2", "work"]
    # JARVIS_MEMORY_DIR is honoured like install_root honours it
    other = tmp_path / "other"
    (tmp_path / "other-profiles" / "solo").mkdir(parents=True)
    env = _env(JARVIS_MEMORY_DIR=str(other))
    assert sorted(_complete(shell, script, "-p", "", env=env)) == ["default", "solo"]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_parser_without_profile_option_has_no_profile_completion(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    parser = argparse.ArgumentParser()
    parser.add_subparsers().add_parser("only")
    script = _script(tmp_path, shell, parser)
    assert "JARVIS_HOME" not in script.read_text()
    assert _complete(shell, script, "-p", "") == []


# ── H574: the CLI's -p/--profile option ──────────────────────────────────────

def test_verb_index_skips_leading_profile_forms():
    assert _verb_index(["kanban", "list"]) == 0
    assert _verb_index(["-p", "work", "kanban", "list"]) == 2
    assert _verb_index(["--profile", "work", "kanban"]) == 2
    assert _verb_index(["--profile=work", "kanban"]) == 1
    assert _verb_index(["-pwork", "kanban"]) == 1


def test_profile_option_reaches_the_verbs_environment():
    seen = {}

    class _Stop(Exception):
        pass

    def factory(environ):
        seen.update(environ)
        raise _Stop

    ctx = Context(environ={"JARVIS_HOME": "/srv/nerva"}, out=io.StringIO(), err=io.StringIO(),
                  client_factory=factory)
    with pytest.raises(_Stop):
        main(["-p", "work", "status"], context=ctx)
    assert seen == {"JARVIS_HOME": "/srv/nerva", "JARVIS_PROFILE": "work"}
    assert "JARVIS_PROFILE" not in ctx.environ                  # the caller's context is untouched


@pytest.mark.parametrize("bad", ["Bad!", "UPPER", "a" * 33])
def test_invalid_profile_name_is_a_usage_error(bad, capsys):
    ctx = Context(environ={}, out=io.StringIO(), err=io.StringIO())
    assert main(["--profile", bad, "status"], context=ctx) == 2
    assert "not a profile name" in capsys.readouterr().err


def test_profile_option_selects_the_profiles_data_root_in_a_real_run(tmp_path):
    home = tmp_path / "home"
    backups = tmp_path / "home-profiles" / "work" / "backups"
    backups.mkdir(parents=True)
    (backups / "jarvis-backup-20261021.tar.gz").write_bytes(b"x")
    repo = Path(__file__).resolve().parents[1]

    def nerva(*args):
        run = subprocess.run([sys.executable, "-m", "agents.cli.nerva", *args], cwd=repo,
                             capture_output=True, text=True, timeout=60,
                             env=_env(JARVIS_HOME=str(home), JARVIS_TESTING="1"))
        assert run.returncode == 0, run.stderr
        return [row["name"] for row in json.loads(run.stdout)["backups"]]

    assert nerva("-p", "work", "backup", "list", "--json") == ["jarvis-backup-20261021.tar.gz"]
    assert nerva("backup", "list", "--json") == []


def test_profile_is_applied_before_the_parser_imports_verb_modules(monkeypatch):
    """build_parser() imports verb modules that fix data-root paths at import
    (agents.core.secrets.DEFAULT_STORE, the kanban stores): the profile must already be
    in the environment when it runs."""
    from agents.cli import nerva

    seen = {}

    class _Stop(Exception):
        pass

    def spy():
        seen["profile"] = os.environ.get("JARVIS_PROFILE")
        raise _Stop

    # main() writes os.environ directly; record the real value first so teardown restores it.
    monkeypatch.setenv("JARVIS_PROFILE", "")
    monkeypatch.setattr(nerva, "build_parser", spy)
    for argv in (["-p", "work", "doctor"], ["--profile=work", "doctor"], ["-pwork", "doctor"],
                 ["--profile", "work", "doctor"]):
        monkeypatch.delenv("JARVIS_PROFILE", raising=False)
        with pytest.raises(_Stop):
            nerva.main(argv)
        assert seen["profile"] == "work", argv
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    with pytest.raises(_Stop):
        nerva.main(["-p", "Bad!", "doctor"])          # left for argparse to refuse
    assert seen["profile"] is None


def test_abbreviated_profile_option_is_refused_not_misparsed(capsys):
    ctx = Context(environ={}, out=io.StringIO(), err=io.StringIO())
    assert main(["--prof", "work", "kanban", "list"], context=ctx) == 2
    assert main(["--pro=work", "kanban", "list"], context=ctx) == 2


def test_profile_option_routes_secrets_to_the_profiles_store(tmp_path):
    """`nerva -p work secrets op set …` used to write the default profile's store."""
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "home-profiles" / "work").mkdir(parents=True)
    repo = Path(__file__).resolve().parents[1]

    def nerva(*args, **extra):
        run = subprocess.run([sys.executable, "-m", "agents.cli.nerva", *args], cwd=repo,
                             capture_output=True, text=True, timeout=60,
                             env=_env(JARVIS_HOME=str(home), JARVIS_TESTING="1",
                                      JARVIS_KEY_DIR=str(tmp_path / "keys"), **extra))
        assert run.returncode == 0, run.stderr
        return run.stdout

    assert "FOO_TOKEN" in nerva("-p", "work", "secrets", "op", "set", "FOO_TOKEN", "op://vault/item/field")
    assert (tmp_path / "home-profiles" / "work" / "security" / "secrets.enc").exists()
    assert not (home / "security" / "secrets.enc").exists()
    assert "references: 1" in nerva("secrets", "op", "status", JARVIS_PROFILE="work")
    assert "references: 0" in nerva("secrets", "op", "status")
