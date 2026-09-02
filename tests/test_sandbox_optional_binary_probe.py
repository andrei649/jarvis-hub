"""An optional host tool that is simply not installed is not an incident.

From a real Windows startup log:

    WARNING jarvis.sandbox  wasmtime availability check failed — WASM sandbox unavailable
    Traceback (most recent call last):
      ...
    FileNotFoundError: [WinError 2] The system cannot find the file specified

Nothing was wrong. `Sandbox`'s own class comment promises the WASM backend
"degrades silently to the existing Docker/subprocess path (no behavior change)"
when wasmtime is absent — but the probe logged every failure with
`exc_info=True`, so the supported configuration announced itself as a traceback
on every boot. Docker had the identical shape.

A traceback still belongs to a probe that fails for an *unexpected* reason.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.sandbox import Sandbox  # noqa: E402

PROBE = Sandbox._probe_binary


def _run_raising(exc):
    def _run(*_args, **_kwargs):
        raise exc

    return _run


class _Completed:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_a_missing_binary_is_one_clean_line(caplog, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _run_raising(FileNotFoundError(2, "not found"))
    )

    with caplog.at_level(logging.DEBUG, logger="jarvis.sandbox"):
        assert PROBE(["wasmtime", "--version"], "the WASM sandbox is unavailable") is False

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.INFO, "an absent optional tool is not a warning"
    assert record.exc_info is None, "no traceback for a supported configuration"
    assert "wasmtime" in record.message
    assert "the WASM sandbox is unavailable" in record.message


def test_an_unexpected_failure_keeps_its_traceback(caplog, monkeypatch):
    """The distinction is the point: only 'not installed' is routine."""
    monkeypatch.setattr(subprocess, "run", _run_raising(PermissionError("denied")))

    with caplog.at_level(logging.DEBUG, logger="jarvis.sandbox"):
        assert PROBE(["docker", "info"], "falling back") is False

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is not None


def test_a_hung_daemon_keeps_its_traceback(caplog, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _run_raising(subprocess.TimeoutExpired("docker", 5))
    )

    with caplog.at_level(logging.DEBUG, logger="jarvis.sandbox"):
        assert PROBE(["docker", "info"], "falling back") is False

    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is not None


def test_an_installed_but_failing_tool_is_reported_without_a_traceback(caplog, monkeypatch):
    """`docker info` returning non-zero (daemon stopped) is an ordinary state."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Completed(1))

    with caplog.at_level(logging.DEBUG, logger="jarvis.sandbox"):
        assert PROBE(["docker", "info"], "falling back") is False

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.INFO
    assert caplog.records[0].exc_info is None


def test_a_working_tool_is_silent(caplog, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Completed(0))

    with caplog.at_level(logging.DEBUG, logger="jarvis.sandbox"):
        assert PROBE(["wasmtime", "--version"], "unused") is True

    assert caplog.records == []


@pytest.mark.parametrize("check,binary", [("_check_docker", "docker"), ("_check_wasmtime", "wasmtime")])
def test_both_optional_tools_go_through_the_same_probe(monkeypatch, check, binary):
    seen: list[list[str]] = []

    def _run(argv, **_kwargs):
        seen.append(argv)
        raise FileNotFoundError(2, "not found")

    monkeypatch.setattr(subprocess, "run", _run)
    sandbox = Sandbox.__new__(Sandbox)

    assert getattr(sandbox, check)() is False
    assert seen and seen[0][0] == binary
