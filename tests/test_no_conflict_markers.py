"""No tracked file carries an unresolved merge-conflict block.

The 2026-09-23 merge train landed ``docs/hermes/build-queue.md`` and
``docs/HERMES_SPRINT.md`` on ``main`` with their conflict blocks still in them:
both sides of every hunk, the markers included, rendered as the published build
queue. Nothing failed, because nothing parsed those files. This test is that
parse, for every tracked file: a line opening or closing a conflict block is
refused. The lone separator line is not searched for, since a Markdown setext
heading underline looks the same.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Built rather than written out, so this file is not a match for its own search.
OPENER, CLOSER = "<" * 7 + " ", ">" * 7 + " "


def _tracked_conflict_lines() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    found = subprocess.run(
        ["git", "grep", "-n", "-I", "-E", f"^({OPENER}|{CLOSER})"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    # git grep exits 1 when nothing matches, 0 when something does.
    assert found.returncode in (0, 1), found.stderr
    return found.stdout.splitlines()


def test_no_tracked_file_holds_a_conflict_block():
    hits = _tracked_conflict_lines()
    assert hits == [], "unresolved merge-conflict markers:\n" + "\n".join(hits[:20])


def test_the_search_finds_a_conflict_block_when_one_is_there(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "doc.md").write_text(f"intro\n{OPENER}HEAD\nours\n=======\ntheirs\n{CLOSER}main\n", encoding="utf-8")
    subprocess.run(["git", "add", "doc.md"], cwd=repo, check=True)
    found = subprocess.run(["git", "grep", "-n", "-I", "-E", f"^({OPENER}|{CLOSER})"],
                           cwd=repo, capture_output=True, text=True, check=False)
    assert found.returncode == 0
    assert [line.split(":")[1] for line in found.stdout.splitlines()] == ["2", "6"]
