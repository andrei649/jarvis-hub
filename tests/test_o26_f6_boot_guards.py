"""
test_o26_f6_boot_guards.py — ORIZONT 26 P0.6 (finding F6).

Two documented entry points, one enforced: `serve.py` ran the fail-closed
boot guards (unauthenticated-external-bind refusal, hardened-profile
preconditions) while `python -m uvicorn agents.web:app` skipped them — a
"hardened" box could start with an unkeyed, forgeable audit chain and never
know. The guards now live in `agents/core/boot_guards.py`, run from the app
lifespan, and stay re-exported from serve.py.
"""

import inspect
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import boot_guards  # noqa: E402


def _clean_env(monkeypatch):
    for var in ("JARVIS_USER_TOKEN", "JARVIS_ADMIN_TOKEN",
                "JARVIS_ALLOW_INSECURE_BIND", "JARVIS_HARDENED",
                "JARVIS_AUDIT_KEY", "JARVIS_HOST"):
        monkeypatch.delenv(var, raising=False)


# ── assert_safe_bind ─────────────────────────────────────────────────────────

def test_loopback_binds_always_allowed(monkeypatch):
    _clean_env(monkeypatch)
    for host in ("127.0.0.1", "localhost", "::1", ""):
        boot_guards.assert_safe_bind(host)  # must not raise


def test_external_bind_without_auth_refuses_to_start(monkeypatch):
    _clean_env(monkeypatch)
    with pytest.raises(SystemExit):
        boot_guards.assert_safe_bind("0.0.0.0")


def test_external_bind_with_token_allowed(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("JARVIS_USER_TOKEN", "tok")
    boot_guards.assert_safe_bind("0.0.0.0")


def test_external_bind_with_explicit_ack_allowed(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("JARVIS_ALLOW_INSECURE_BIND", "1")
    boot_guards.assert_safe_bind("0.0.0.0")


# ── assert_hardened_posture ──────────────────────────────────────────────────

def test_hardened_without_audit_key_refuses_to_start(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    with pytest.raises(SystemExit):
        boot_guards.assert_hardened_posture()


def test_hardened_with_audit_key_starts(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "k" * 32)
    boot_guards.assert_hardened_posture()  # must not raise


def test_unhardened_is_a_noop(monkeypatch):
    _clean_env(monkeypatch)
    boot_guards.assert_hardened_posture()


# ── the composed lifespan entry ──────────────────────────────────────────────

def test_enforce_boot_posture_reads_jarvis_host(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("JARVIS_HOST", "0.0.0.0")
    with pytest.raises(SystemExit):
        boot_guards.enforce_boot_posture()
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "tok")
    boot_guards.enforce_boot_posture()  # authenticated → allowed


def test_default_env_is_a_noop(monkeypatch):
    _clean_env(monkeypatch)
    boot_guards.enforce_boot_posture()


# ── wiring pins (no app boot needed) ─────────────────────────────────────────

def test_web_lifespan_calls_the_guards():
    """The uvicorn entry point must enforce the same posture as serve.py."""
    from agents import web

    src = inspect.getsource(web.lifespan)
    assert "enforce_boot_posture" in src, (
        "F6 regression: the app lifespan no longer runs the boot guards — "
        "the raw-uvicorn entry would silently skip them again"
    )


def test_serve_reexports_stay_importable():
    """Existing consumers import the guards from serve.py — keep that surface."""
    import serve

    assert serve.assert_safe_bind is boot_guards.assert_safe_bind
    assert serve.assert_hardened_posture is boot_guards.assert_hardened_posture
