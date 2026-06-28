"""CDX-12 — the "Design-Partner / Hardened" profile (opt-in, default-off).

A single ``JARVIS_HARDENED=1`` switch tightens four toggles at once:
  1. guardrails default WARN -> REDACT
  2. JARVIS_AUDIT_KEY required (startup fails closed without it)
  3. strict egress forced (the JARVIS_STRICT_EGRESS=0 downgrade is ignored)
  4. mutating MCP route tools forced off
…and it turns on CDX-11 plugin least-privilege. Default OFF: with the env unset,
every toggle is exactly its pre-CDX-12 value.
"""

import pytest

from agents.core.security import hardened


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Each test owns the hardened/audit env explicitly.
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)


# ── default off: nothing changes ──────────────────────────────────────────────
def test_default_off_is_all_permissive():
    assert hardened.enabled() is False
    assert hardened.guardrails_default() == "WARN"
    assert hardened.strict_egress_forced() is False
    assert hardened.mutating_mcp_blocked() is False
    assert hardened.audit_key_required() is False
    assert hardened.missing_audit_key() is False
    assert hardened.enforce() == []


# ── hardened on: every toggle tightens ────────────────────────────────────────
def test_hardened_on_tightens_every_toggle(monkeypatch):
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    assert hardened.enabled() is True
    assert hardened.guardrails_default() == "REDACT"
    assert hardened.strict_egress_forced() is True
    assert hardened.mutating_mcp_blocked() is True
    assert hardened.audit_key_required() is True


def test_accepts_common_truthy_spellings(monkeypatch):
    for val in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("JARVIS_HARDENED", val)
        assert hardened.enabled() is True
    for val in ("0", "false", "no", "", "off"):
        monkeypatch.setenv("JARVIS_HARDENED", val)
        assert hardened.enabled() is False


# ── audit-key requirement is fail-closed ──────────────────────────────────────
def test_hardened_without_audit_key_is_a_fatal_violation(monkeypatch):
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    assert hardened.missing_audit_key() is True
    problems = hardened.enforce()
    assert problems and any("JARVIS_AUDIT_KEY" in p for p in problems)


def test_hardened_with_audit_key_passes(monkeypatch):
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "s3cret-off-box-key")
    assert hardened.missing_audit_key() is False
    assert hardened.enforce() == []


def test_serve_assert_hardened_posture_fails_closed(monkeypatch):
    import serve
    monkeypatch.setenv("JARVIS_HARDENED", "1")  # no audit key
    with pytest.raises(SystemExit):
        serve.assert_hardened_posture()
    # …and is a no-op once the key is present
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "k")
    serve.assert_hardened_posture()


# ── posture snapshot shape ────────────────────────────────────────────────────
def test_posture_reports_all_toggles(monkeypatch):
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "k")
    p = hardened.posture()
    assert p == {
        "enabled": True,
        "guardrails_mode_default": "REDACT",
        "audit_key_required": True,
        "audit_key_present": True,
        "strict_egress_forced": True,
        "mutating_mcp_blocked": True,
        "plugin_least_privilege": True,
    }


# ── toggle 3: strict egress forced even when the downgrade env is set ──────────
def test_hardened_forces_strict_egress_over_downgrade(monkeypatch):
    from agents.core.http_client import PluginEgressError, PluginHTTPClient
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")   # operator tries to downgrade
    monkeypatch.setenv("JARVIS_HARDENED", "1")        # hardened overrides → strict
    c = PluginHTTPClient.for_plugin("weather")        # RESTRICTED → wttr.in only
    with pytest.raises(PluginEgressError):
        c._enforce_egress("https://evil.example/x")


def test_downgrade_still_works_when_not_hardened(monkeypatch):
    from agents.core.http_client import PluginHTTPClient
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    c = PluginHTTPClient.for_plugin("weather")
    c._enforce_egress("https://evil.example/x")        # warns, does not raise


# ── toggle 4: mutating MCP forced off ─────────────────────────────────────────
def test_hardened_forces_mutating_mcp_off(monkeypatch):
    from agents.core.mcp import route_tools
    monkeypatch.setenv("JARVIS_MCP_MUTATING_TOOLS", "1")  # operator tries to enable
    monkeypatch.setenv("JARVIS_HARDENED", "1")            # hardened forces off
    assert route_tools.mutating_tools_enabled() is False
    # without hardening the switch is honored again
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    assert route_tools.mutating_tools_enabled() is True


# ── cross-check: CDX-11 plugin least-privilege rides the same preset ───────────
def test_hardened_enables_plugin_least_privilege(monkeypatch):
    from agents.core.plugin_gate import PermissionGate
    monkeypatch.delenv("JARVIS_PLUGIN_LEAST_PRIVILEGE", raising=False)
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    gate = PermissionGate()
    assert gate.least_privilege is True
    # external-write wildcard withheld under the preset
    assert gate.check_call("social_x", "nobody-special") is False
