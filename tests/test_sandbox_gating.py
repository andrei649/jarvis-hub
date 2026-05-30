"""Tests for sandbox security gating — subprocess disabled by default, dev mode gate."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.sandbox import Sandbox


@pytest.mark.asyncio
async def test_subprocess_disabled_by_default():
    sandbox = Sandbox(allow_subprocess=False)
    result = await sandbox.execute_python("print('hello')")
    assert not result.success
    assert "disabled" in result.stderr.lower()


@pytest.mark.asyncio
async def test_shell_disabled_by_default():
    sandbox = Sandbox(allow_subprocess=False)
    result = await sandbox.execute_shell("echo hello")
    assert not result.success
    assert "disabled" in result.stderr.lower()


@pytest.mark.asyncio
async def test_subprocess_allowed_when_enabled():
    sandbox = Sandbox(allow_subprocess=True)
    result = await sandbox.execute_python("print('hello')")
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_shell_allowed_when_enabled():
    sandbox = Sandbox(allow_subprocess=True)
    result = await sandbox.execute_shell("echo hello")
    assert result.exit_code == 0


def test_docker_check_does_not_crash():
    sandbox = Sandbox()
    assert sandbox._has_docker is False or sandbox._has_docker is True
