"""H004: Bash and Zsh offer only children of the current argparse node."""

from __future__ import annotations

import argparse
import shutil
import subprocess

import pytest

from agents.cli.nerva import build_parser, completion_script


def _script(tmp_path, shell, parser):
    path = tmp_path / f"nerva.{shell}"
    path.write_text(completion_script(shell, parser), encoding="utf-8")
    return path


def _complete(shell, script, *words):
    if shell == "bash":
        body = r'''source "$1"
shift
COMP_WORDS=(nerva "$@")
COMP_CWORD=$((${#COMP_WORDS[@]} - 1))
_nerva
printf '%s\n' "${COMPREPLY[@]}"'''
        argv = ["bash", "--noprofile", "--norc", "-c", body, "bash", str(script), *words]
    else:
        body = r'''compadd() {
  [[ "$1" == "--" ]] || return 2
  shift
  local candidate
  for candidate in "$@"; do
    [[ "$candidate" == "${words[CURRENT]}"* ]] && print -r -- "$candidate"
  done
}
source "$1"
shift
words=(nerva "$@")
CURRENT=${#words}
_nerva'''
        argv = ["zsh", "-f", "-c", body, "zsh", str(script), *words]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
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
