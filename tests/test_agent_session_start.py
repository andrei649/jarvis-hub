"""Regression tests for the remote AI session bootstrap hook."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / ".claude" / "hooks" / "session-start.sh"


def _fake_npm(bin_dir: Path) -> Path:
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$NPM_CALL_LOG\"\n"
        "mkdir -p node_modules\n",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    return npm


def _run_hook(project: Path, bin_dir: Path, call_log: Path, *, remote: bool = True):
    env = {
        **os.environ,
        "CLAUDE_CODE_REMOTE": "true" if remote else "false",
        "CLAUDE_PROJECT_DIR": str(project),
        "NPM_CALL_LOG": str(call_log),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    return subprocess.run(
        ["bash", str(HOOK)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_remote_bootstrap_uses_lockfile_cache(tmp_path):
    project = tmp_path / "repo"
    workspace = project / "worldview"
    workspace.mkdir(parents=True)
    lockfile = workspace / "package-lock.json"
    lockfile.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_npm(bin_dir)
    call_log = tmp_path / "npm-calls.log"

    first = _run_hook(project, bin_dir, call_log)
    assert first.returncode == 0, first.stderr
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "ci --no-audit --no-fund --loglevel=error"
    ]
    assert (workspace / "node_modules" / ".jarvis-package-lock.sha256").is_file()

    second = _run_hook(project, bin_dir, call_log)
    assert second.returncode == 0, second.stderr
    assert "already match" in second.stderr
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 1

    lockfile.write_text('{"lockfileVersion": 3, "changed": true}\n', encoding="utf-8")
    third = _run_hook(project, bin_dir, call_log)
    assert third.returncode == 0, third.stderr
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 2


def test_local_session_does_not_install(tmp_path):
    project = tmp_path / "repo"
    (project / "worldview").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_npm(bin_dir)
    call_log = tmp_path / "npm-calls.log"

    result = _run_hook(project, bin_dir, call_log, remote=False)

    assert result.returncode == 0
    assert not call_log.exists()
