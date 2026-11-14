"""H084: literal project-relative filters for the owner /diff command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import worktrees
from agents.core.channels import outbound_safety
from agents.core.commands import Principal, build_default_registry

OWNER = Principal(channel="web", admin=True)
GUEST = Principal(channel="web", admin=False)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True, timeout=10).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text("app before\n", encoding="utf-8")
    (root / "other.py").write_text("other before\n", encoding="utf-8")
    (root / "space name.txt").write_text("space before\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "app.py").write_text("sub before\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=T",
         "commit", "-q", "-m", "base")
    monkeypatch.setattr(worktrees, "session_tree_or_none", lambda _session: None)
    return root


def _orch(root: Path):
    return SimpleNamespace(session_id="session-1",
                           get_setting=lambda key, default="": str(root) if key == "llm.project_dir" else default)


async def _reply(root: Path, text: str, principal=OWNER):
    return await build_default_registry().dispatch(text, orch=_orch(root), principal=principal)


async def test_working_filter_and_untracked_names_are_isolated(repo):
    (repo / "app.py").write_text("app after\n", encoding="utf-8")
    (repo / "other.py").write_text("other after\n", encoding="utf-8")
    (repo / "app-new.txt").write_text("untracked app\n", encoding="utf-8")
    (repo / "other-new.txt").write_text("untracked other\n", encoding="utf-8")
    reply = (await _reply(repo, "/diff app.py app-new.txt")).reply
    assert "+app after" in reply and "+other after" not in reply
    assert "app-new.txt" in reply and "other-new.txt" not in reply


async def test_staged_all_and_stat_filters(repo):
    (repo / "app.py").write_text("app staged\n", encoding="utf-8")
    (repo / "other.py").write_text("other staged\n", encoding="utf-8")
    _git(repo, "add", "app.py", "other.py")
    (repo / "app.py").write_text("app working\n", encoding="utf-8")
    staged = (await _reply(repo, "/diff staged app.py")).reply
    all_diff = (await _reply(repo, "/diff all app.py")).reply
    stat = (await _reply(repo, "/diff all --stat app.py")).reply
    assert "+app staged" in staged and "app working" not in staged
    assert "+app working" in all_diff and "other staged" not in all_diff
    assert "app.py" in stat and "other.py" not in stat and "+app working" not in stat


@pytest.mark.parametrize("alias", ["staged", "--staged", "cached", "--cached", "STAGED"])
async def test_staged_option_aliases_preserve_existing_behavior(repo, alias):
    (repo / "app.py").write_text("app staged\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    (repo / "app.py").write_text("app working\n", encoding="utf-8")
    reply = (await _reply(repo, f"/diff {alias} app.py")).reply
    assert "+app staged" in reply and "app working" not in reply


@pytest.mark.parametrize("alias", ["all", "--all", "head", "HEAD"])
async def test_all_option_aliases_preserve_existing_behavior(repo, alias):
    (repo / "app.py").write_text("app after\n", encoding="utf-8")
    reply = (await _reply(repo, f"/diff {alias} app.py")).reply
    assert "+app after" in reply


@pytest.mark.parametrize("alias", ["--stat", "stat", "STAT"])
async def test_stat_option_aliases_preserve_existing_behavior(repo, alias):
    (repo / "app.py").write_text("app after\n", encoding="utf-8")
    reply = (await _reply(repo, f"/diff {alias} app.py")).reply
    assert "app.py" in reply and "+app after" not in reply


async def test_project_subdirectory_filters_are_repo_relative(repo):
    (repo / "app.py").write_text("top after\n", encoding="utf-8")
    (repo / "sub" / "app.py").write_text("sub after\n", encoding="utf-8")
    (repo / "sub" / "new.txt").write_text("sub new\n", encoding="utf-8")
    (repo / "top-new.txt").write_text("top new\n", encoding="utf-8")
    reply = (await _reply(repo / "sub", "/diff app.py new.txt")).reply
    assert "+sub after" in reply and "+top after" not in reply
    assert "sub/new.txt" in reply and "top-new.txt" not in reply


async def test_quoted_spaces_directory_and_case_are_literal(repo):
    (repo / "space name.txt").write_text("space after\n", encoding="utf-8")
    (repo / "sub" / "app.py").write_text("sub after\n", encoding="utf-8")
    reply = (await _reply(repo, '/diff "space name.txt" sub')).reply
    assert "+space after" in reply and "+sub after" in reply
    assert "+app before" not in reply
    wrong_case = (await _reply(repo, "/diff APP.PY")).reply
    assert "space after" not in wrong_case and "sub after" not in wrong_case


@pytest.mark.parametrize("args", [
    "../app.py", "/tmp/app.py", "C:app.py", "a\\b", "app*.py", ":(top)app.py",
    "a//b", "a/./b", "--stat app.py --stat", "app.py staged", "app.py --",
    "app.py\nother.py", "app.py\x00", "\"unterminated", "a" * 257,
    " ".join(f"p{i}" for i in range(9)), "é" * 1025, "--", "\ud800",
])
async def test_invalid_input_is_refused_before_git(repo, monkeypatch, args):
    calls = []
    monkeypatch.setattr(worktrees, "run_git", lambda *_a, **_k: calls.append(True))
    outcome = await _reply(repo, "/diff " + args)
    assert "Usage" in outcome.reply and not calls


async def test_double_dash_disambiguates_option_named_file(repo):
    (repo / "staged").write_text("new file\n", encoding="utf-8")
    reply = (await _reply(repo, "/diff -- staged")).reply
    assert "staged" in reply
    assert "No tracked changes for staged" not in reply


async def test_owner_gate_precedes_path_validation(repo):
    result = await _reply(repo, "/diff ../secret", principal=GUEST)
    assert result.status == "refused" and "Usage" not in result.reply


async def test_selected_diff_is_redacted_before_display(repo, monkeypatch):
    secret = "private-" + "x" * 100
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda text: text.replace(secret, "[REDACTED:known]"))
    (repo / "app.py").write_text(secret + "\n", encoding="utf-8")
    (repo / "other.py").write_text("other changed\n", encoding="utf-8")
    reply = (await _reply(repo, "/diff app.py")).reply
    assert "[REDACTED:known]" in reply and secret not in reply
    assert "other changed" not in reply


async def test_symlink_replacement_does_not_read_outside_body(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_text("private outside body\n", encoding="utf-8")
    (repo / "sub" / "app.py").unlink()
    (repo / "sub").rmdir()
    (repo / "sub").symlink_to(outside, target_is_directory=True)
    reply = (await _reply(repo, "/diff sub/app.py")).reply
    assert "private outside body" not in reply
    assert "-sub before" in reply
