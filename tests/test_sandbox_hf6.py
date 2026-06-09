"""HF-6 — sandbox isolation posture is explicit and host-exec is surfaced.

The host fallback (`allow_subprocess`) is a per-instance opt-in, never a global
env flag, and `security_status()` exposes when code would run on the host without
isolation so the HUD / `/status` can warn.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.sandbox import Sandbox


def _docker_available():
    return Sandbox()._has_docker


def test_disabled_backend_is_not_isolated_but_not_insecure():
    """No Docker/WASM + host fallback off → 'disabled': nothing runs, nothing leaks."""
    sb = Sandbox(allow_subprocess=False, allow_wasm=False)
    if sb._has_docker:
        pytest.skip("Docker available — disabled-backend case only applies without Docker")
    s = sb.security_status()
    assert s["backend"] == "disabled"
    assert s["isolated"] is False
    assert s["insecure_host_exec"] is False
    assert s["warning"] == ""
    assert sb.is_isolated() is False


def test_host_fallback_flagged_insecure_with_warning():
    """allow_subprocess=True + no Docker/WASM → host exec, flagged loudly."""
    sb = Sandbox(allow_subprocess=True, allow_wasm=False)
    if sb._has_docker:
        pytest.skip("Docker available — host-fallback case only applies without Docker")
    s = sb.security_status()
    assert s["backend"] == "subprocess-host"
    assert s["isolated"] is False
    assert s["insecure_host_exec"] is True
    assert "HF-6" in s["warning"]
    assert sb.allow_subprocess is True


def test_docker_backend_is_isolated_when_present():
    sb = Sandbox()
    if not sb._has_docker:
        pytest.skip("Docker not available on this runner")
    s = sb.security_status()
    assert s["backend"] == "docker"
    assert s["isolated"] is True
    assert s["insecure_host_exec"] is False


def test_host_fallback_is_not_driven_by_dev_mode_env(monkeypatch):
    """Setting DEV_MODE must NOT silently enable host execution — only the
    explicit per-instance allow_subprocess flag does (HF-6: no global flag)."""
    monkeypatch.setenv("DEV_MODE", "1")
    sb = Sandbox()  # default allow_subprocess=False
    assert sb.allow_subprocess is False
    if not sb._has_docker:
        assert sb.active_backend() in ("disabled", "wasm")
        assert sb.security_status()["insecure_host_exec"] is False
