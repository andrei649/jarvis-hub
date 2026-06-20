"""Tests for the rclone Drive "AI" import (private personalization).

Offline: the rclone subprocess is replaced with an injected fake runner, so no
network, no binary, no real Drive. Verifies the command built, success/failure
summaries, env parsing, and the gitignored default destination.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.drive_sync import DriveAISync


def _runner(calls, *, code=0, out="", err=""):
    async def run(argv):
        calls.append(argv)
        return code, out, err
    return run


async def test_builds_rclone_command_and_succeeds(tmp_path):
    calls = []
    dest = tmp_path / "drive_ai"
    s = DriveAISync("gdrive:AI", dest, runner=_runner(calls))
    summary = await s.sync()

    assert summary["ok"] is True
    assert summary["remote"] == "gdrive:AI"
    assert summary["dest"] == str(dest)
    argv = calls[0]
    assert argv[:4] == ["rclone", "copy", "gdrive:AI", str(dest)]
    assert "--fast-list" in argv
    assert dest.exists()                      # dest created before transfer


async def test_failure_returns_error_summary(tmp_path):
    s = DriveAISync("gdrive:AI", tmp_path / "d",
                    runner=_runner([], code=1, err="permission denied"))
    summary = await s.sync()
    assert summary["ok"] is False
    assert "permission denied" in summary["error"]


async def test_missing_remote_is_a_clean_failure(tmp_path):
    s = DriveAISync("", tmp_path / "d", runner=_runner([]))
    summary = await s.sync()
    assert summary["ok"] is False
    assert "JARVIS_DRIVE_AI_REMOTE" in summary["error"]


async def test_rclone_not_installed_is_handled(tmp_path):
    async def boom(argv):
        raise FileNotFoundError("rclone")
    s = DriveAISync("gdrive:AI", tmp_path / "d", runner=boom)
    summary = await s.sync()
    assert summary["ok"] is False
    assert "rclone not installed" in summary["error"]


def test_from_env_defaults_to_gitignored_data_path(monkeypatch):
    monkeypatch.setenv("JARVIS_DRIVE_AI_REMOTE", "gdrive:AI")
    monkeypatch.delenv("JARVIS_DRIVE_AI_DEST", raising=False)
    s = DriveAISync.from_env()
    # Default dest lives under the data_path root (memory_logs/, gitignored).
    assert s.remote == "gdrive:AI"
    assert "drive_ai" in str(s.dest)
    assert s.mode == "copy"


def test_from_env_respects_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DRIVE_AI_REMOTE", "g:AI")
    monkeypatch.setenv("JARVIS_DRIVE_AI_DEST", str(tmp_path / "x"))
    monkeypatch.setenv("JARVIS_DRIVE_AI_MODE", "sync")
    monkeypatch.setenv("JARVIS_DRIVE_AI_FLAGS", "--checksum --transfers 8")
    s = DriveAISync.from_env()
    assert s.mode == "sync"
    assert s.argv()[:4] == ["rclone", "sync", "g:AI", str(tmp_path / "x")]
    assert "--checksum" in s.flags and "--transfers" in s.flags


def test_available_requires_remote(monkeypatch, tmp_path):
    # No remote → not available regardless of rclone presence.
    assert DriveAISync("", tmp_path).available() is False
