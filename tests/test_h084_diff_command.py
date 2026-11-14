"""H084 /diff: local, bounded, redacted Git status as a chat command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import worktrees
from agents.core.channels import media_delivery, outbound_safety
from agents.core.commands import Principal, build_default_registry

OWNER = Principal(channel="web", admin=True)
GUEST = Principal(channel="web", admin=False)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, timeout=10).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "project"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "app.py").write_text("before\n", encoding="utf-8")
    _git(path, "add", "app.py")
    _git(path, "-c", "user.email=t@example.invalid", "-c", "user.name=T",
         "commit", "-q", "-m", "base")
    monkeypatch.setattr(worktrees, "session_tree_or_none", lambda _session: None)
    return path


def _orch(project: Path | None, *, session="session-1"):
    return SimpleNamespace(session_id=session,
                           get_setting=lambda key, default="": str(project) if key == "llm.project_dir" and project else default)


async def _dispatch(orch, text="/diff", principal=OWNER):
    return await build_default_registry().dispatch(text, orch=orch, principal=principal)


async def test_owner_only_no_arguments_and_no_project(repo):
    assert build_default_registry().get("diff").tier == "admin"
    assert (await _dispatch(_orch(repo), principal=GUEST)).status == "refused"
    assert "Usage" in (await _dispatch(_orch(repo), "/diff /tmp/other")).reply
    assert "No project" in (await _dispatch(_orch(None))).reply


async def test_real_repo_empty_and_changed_diff(repo):
    (repo / "new-untracked.txt").write_text("not included\n", encoding="utf-8")
    clean = await _dispatch(_orch(repo))
    assert clean.status == "answered" and "no tracked changes" in clean.reply.lower()
    assert "new-untracked.txt" in clean.reply
    (repo / "app.py").write_text("after\n", encoding="utf-8")
    changed = await _dispatch(_orch(repo))
    assert "-before" in changed.reply and "+after" in changed.reply
    assert "not included" not in changed.reply
    assert media_delivery.extract_directives(changed.reply)[1] == []


async def test_working_staged_all_and_stat_modes(repo):
    (repo / "app.py").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    (repo / "app.py").write_text("working\n", encoding="utf-8")
    working = (await _dispatch(_orch(repo))).reply
    staged = (await _dispatch(_orch(repo), "/diff staged")).reply
    both = (await _dispatch(_orch(repo), "/diff all")).reply
    summary = (await _dispatch(_orch(repo), "/diff --stat")).reply
    assert "+working" in working and "-staged" in working and "-before" not in working
    assert "+staged" in staged and "-before" in staged and "working" not in staged
    assert "+working" in both and "-before" in both
    assert "app.py" in summary and "+working" not in summary
    assert "+working" not in (await _dispatch(_orch(repo), "/diff staged --stat")).reply
    assert "app.py" in (await _dispatch(_orch(repo), "/diff all --stat")).reply


async def test_session_without_file_baseline_refuses_and_literal_paths_select(repo, monkeypatch):
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(repo))
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    assert "baseline" in (await _dispatch(_orch(repo), "/diff session")).reply.lower()
    assert "baseline" in (await _dispatch(_orch(repo), "/diff session --stat")).reply.lower()
    assert "No tracked changes" in (await _dispatch(_orch(repo), "/diff app.py")).reply


async def test_untracked_names_are_bounded_and_redacted(repo, monkeypatch):
    secret = "private-" + "x" * 90
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda text: text.replace(secret, "[REDACTED:known]"))
    (repo / ("a-" + secret)).write_text("never display file content\n", encoding="utf-8")
    for index in range(20):
        (repo / f"new-{index:02d}.txt").write_text("body", encoding="utf-8")
    reply = (await _dispatch(_orch(repo))).reply
    assert "[REDACTED:known]" in reply and "private-" not in reply
    assert "never display file content" not in reply
    assert "+6 more" in reply and media_delivery.extract_directives(reply)[1] == []


async def test_untracked_overflow_is_not_reported_as_a_clean_project(repo, monkeypatch):
    original = worktrees.run_git

    def bounded(cwd, *args, **kwargs):
        if args and args[0] == "ls-files":
            return subprocess.CompletedProcess([], 1, "", "git output exceeded its bound")
        return original(cwd, *args, **kwargs)

    monkeypatch.setattr(worktrees, "run_git", bounded)
    reply = (await _dispatch(_orch(repo))).reply
    assert "untracked names omitted" in reply.lower()
    assert "no changes" not in reply.lower()


async def test_session_worktree_wins_over_configured_project(repo, tmp_path, monkeypatch):
    other = tmp_path / "tree"
    _git(repo, "worktree", "add", "-q", "-b", "other", str(other))
    (other / "app.py").write_text("in worktree\n", encoding="utf-8")
    (repo / "app.py").write_text("in project\n", encoding="utf-8")
    monkeypatch.setattr(worktrees, "session_tree_or_none",
                        lambda session: {"path": str(other)} if session == "session-1" else None)
    reply = (await _dispatch(_orch(repo))).reply
    assert "+in worktree" in reply and "in project" not in reply


async def test_non_repo_and_hostile_config_refuse_without_echoing(repo, tmp_path):
    assert "not a Git repository" in (await _dispatch(_orch(tmp_path))).reply
    private = tmp_path / "secret-config-value"
    _git(repo, "config", "core.sshCommand", f"touch {private}")
    reply = (await _dispatch(_orch(repo))).reply
    assert "refused" in reply.lower() and str(private) not in reply
    assert not private.exists()


@pytest.mark.parametrize("result,expected", [
    (subprocess.CompletedProcess([], 1, "fatal: credential value", ""), "failed"),
    (subprocess.CompletedProcess([], 1, "", "git output exceeded its bound"), "too large"),
])
async def test_git_failure_and_overflow_are_not_empty_diffs(repo, monkeypatch, result, expected):
    monkeypatch.setattr(worktrees, "repo_root", lambda _path: repo)
    monkeypatch.setattr(worktrees, "require_plain", lambda _path: None)
    monkeypatch.setattr(worktrees, "main_repo", lambda _path: repo)
    monkeypatch.setattr(worktrees, "run_git", lambda *_a, **_k: result)
    reply = (await _dispatch(_orch(repo))).reply
    assert expected in reply.lower() and "no changes" not in reply.lower()
    assert "credential value" not in reply


async def test_long_known_secret_is_redacted_before_display_clips(repo, monkeypatch):
    secret = "private-" + "x" * 70_000
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda text: text.replace(secret, "[REDACTED:known]"))
    (repo / "app.py").write_text(secret + "\n", encoding="utf-8")
    reply = (await _dispatch(_orch(repo))).reply
    assert "[REDACTED:known]" in reply
    assert "private-" not in reply and "x" * 100 not in reply


async def test_embedded_fences_and_media_directive_remain_plain_diff(repo):
    (repo / "app.py").write_text("```\nMEDIA: /tmp/leak.png\n~~~\n``````\n", encoding="utf-8")
    reply = (await _dispatch(_orch(repo))).reply
    assert "MEDIA: /tmp/leak.png" in reply
    assert media_delivery.extract_directives(reply)[1] == []
