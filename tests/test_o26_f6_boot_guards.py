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
                "JARVIS_AUDIT_KEY", "JARVIS_HOST",
                # The front-door guard (Hermes absorption 5b) reads these too; a
                # developer's shell must not leak a bot token into the "clean" cases.
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS", "DISCORD_BOT_TOKEN",
                "SLACK_BOT_TOKEN", "JARVIS_CHANNEL_PAIRING", "JARVIS_CHANNEL_OPEN",
                # The two network-edge lists (Hermes absorption 5b) are parse-checked at
                # boot too; a shell that exports one must not colour the "clean" cases.
                "JARVIS_TRUSTED_PROXIES", "JARVIS_TRUSTED_PROXY", "JARVIS_ALLOWED_HOSTS"):
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


def test_enforce_boot_posture_runs_the_front_door_guard(monkeypatch):
    """A configured bot with pairing switched off and no allowlist is refused from
    the composed entry, not only from the guard called directly (Hermes absorption 5b)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    with pytest.raises(SystemExit):
        boot_guards.enforce_boot_posture()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    boot_guards.enforce_boot_posture()  # allowlisted → guarded → boots
    assert "assert_guarded_channels" in inspect.getsource(boot_guards.enforce_boot_posture)


# ── the network-edge lists are parse-checked from the composed entry ─────────
# (Hermes absorption 5b) A trust-widening list (JARVIS_TRUSTED_PROXIES) or a
# host-accepting list (JARVIS_ALLOWED_HOSTS) that cannot be parsed must stop the
# boot from *every* entry point — the runtime parse already fails closed, but an
# operator who wrote the line deserves to be told it was not understood rather than
# debug a box that silently ignores it.

def test_enforce_boot_posture_refuses_a_malformed_trusted_proxy_list(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8, nonsense")
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.enforce_boot_posture()
    message = str(excinfo.value)
    assert "JARVIS_TRUSTED_PROXIES" in message
    assert "nonsense" not in message and "10.0.0.0/8" not in message
    # the same list spelled correctly boots: it is the parse that refuses, not the knob
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8")
    boot_guards.enforce_boot_posture()


def test_enforce_boot_posture_refuses_a_wildcard_allowed_host(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("JARVIS_ALLOWED_HOSTS", "*")
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.enforce_boot_posture()
    message = str(excinfo.value)
    assert "JARVIS_ALLOWED_HOSTS" in message
    monkeypatch.setenv("JARVIS_ALLOWED_HOSTS", "hub.example.test")
    boot_guards.enforce_boot_posture()  # a bare host name is a valid list → boots


def test_enforce_boot_posture_order_is_pinned():
    """Parse checks first (flags, then the two lists), then the bind, then the front
    door, then the hardened profile — so an unreadable value is refused before any
    guard reasons about the posture it was meant to set."""
    src = inspect.getsource(boot_guards.enforce_boot_posture)
    documented = (
        "assert_parseable_posture_flags(",
        "assert_parseable_trusted_proxies(",
        "assert_parseable_allowed_hosts(",
        "assert_safe_bind(",
        "assert_guarded_channels(",
        "assert_hardened_posture(",
    )
    positions = []
    for name in documented:
        # the *call*, not an import line: an import mentions the name without "("
        assert name in src, f"enforce_boot_posture no longer calls {name}"
        positions.append(src.index(name))
    assert positions == sorted(positions), (
        "enforce_boot_posture runs the guards out of the documented order: "
        + " → ".join(documented)
    )


# ── wiring pins (no app boot needed) ─────────────────────────────────────────

def test_web_lifespan_calls_the_guards():
    """The uvicorn entry point must enforce the same posture as serve.py."""
    from agents import web

    src = inspect.getsource(web.lifespan)
    assert "enforce_boot_posture" in src, (
        "F6 regression: the app lifespan no longer runs the boot guards — "
        "the raw-uvicorn entry would silently skip them again"
    )


def test_front_door_late_pass_refuses_malformed_lists_too(monkeypatch):
    """The two network-edge lists live in .env like the channel tokens, so the late
    pass must parse-check them over the loaded mapping — a value the early pass never
    saw must still stop the boot, naming the variable and never the value."""
    _clean_env(monkeypatch)
    with pytest.raises(SystemExit) as refused:
        boot_guards.assert_front_door({"JARVIS_TRUSTED_PROXIES": "10.0.0.0/8, nonsense"})
    assert "JARVIS_TRUSTED_PROXIES" in str(refused.value) and "nonsense" not in str(refused.value)
    with pytest.raises(SystemExit) as refused:
        boot_guards.assert_front_door({"JARVIS_ALLOWED_HOSTS": "*"})
    assert "JARVIS_ALLOWED_HOSTS" in str(refused.value)
    assert boot_guards.assert_front_door({"JARVIS_TRUSTED_PROXIES": "127.0.0.1/32"}) is None


def test_web_lifespan_runs_the_late_front_door_after_env_load():
    """The early guard runs before load_agents loads .env; the late pass must sit after
    it and before the first channel token is read, or a .env-only bot boots open."""
    from agents import web

    src = inspect.getsource(web.lifespan)
    early = src.index("enforce_boot_posture()")
    loaded = src.index("await orch.load_agents()")
    late = src.index("assert_front_door()")
    first_token = src.index('os.environ.get("TELEGRAM_BOT_TOKEN"')
    assert early < loaded < late < first_token


def test_serve_reexports_stay_importable():
    """Existing consumers import the guards from serve.py — keep that surface."""
    import serve

    assert serve.assert_safe_bind is boot_guards.assert_safe_bind
    assert serve.assert_hardened_posture is boot_guards.assert_hardened_posture
